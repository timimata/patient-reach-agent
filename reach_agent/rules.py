"""Offline, rule-based extractor (Portuguese regular expressions).

Two jobs: the demo runs without an API key, and it is the *baseline* in the eval: the
LLM has to beat it by enough to justify its cost and latency. It was written next to the
eval dataset, so its scores there are optimistic.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, time, timedelta

from .extraction import PARTS_OF_DAY, ExtractionContext
from .models import Extraction, Intent, TimePreference

HANDOFF_PATTERNS = (
    ("clinical_question", r"\b(dor|dores|doi|sangr\w*|febre|sintoma\w*|incha\w*|infe[cç]\w*|alergi\w*"
                          r"|antibiotic\w*|medica\w*|comprimido\w*|gravida|posso tomar|devo tomar)\b"),
    ("complaint", r"\b(reclama\w*|queixa\w*|inaceitavel|pessim\w*|vergonha|mal atendid\w*)\b"),
    ("other", r"\b(cancelar|desmarcar|nao preciso|deixem de|parem de|preco\w*|custa|seguro)\b"),
)
ACCEPT_WORDS = re.compile(r"^(sim|pode ser|ok|okay|combinado|esta bem|confirmo|perfeito|claro|serve)\b")
BOOKING_WORDS = re.compile(r"\b(marca\w*|consulta|vaga|ligu\w*|ligar|contact\w*)\b")
OPTION = re.compile(r"(?:^|\ba\s+|\bopcao\s*)(primeira|segunda|terceira|[1-3])\b")
ORDINALS = {"primeira": 1, "segunda": 2, "terceira": 3}
TIME_BOUND = re.compile(r"\b(depois|a partir|antes|ate)\s+(?:d?[ao]s?\s+)?(\d{1,2})(?:[:h](\d{2}))?")
AT_TIME = re.compile(r"\b(?:as|pelas)\s+(\d{1,2})(?:[:h](\d{2}))?")
PART_OF_DAY = re.compile(r"\b(?:de|da|a|na|pela)\s+(manha|tarde|noite)\b")
WEEKDAYS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
WEEKDAY = re.compile(r"\b(" + "|".join(WEEKDAYS) + r")\b")


def normalize(text: str) -> str:
    """Lowercase, strip accents and collapse spaces: 'Às 18h' -> 'as 18h'."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.split())


PARTS = {normalize(name): bounds for name, bounds in PARTS_OF_DAY.items()}


class RuleBasedExtractor:
    name = "rules"

    def extract(self, message: str, context: ExtractionContext) -> Extraction:
        text = normalize(message)
        for reason, pattern in HANDOFF_PATTERNS:  # safety first, whatever else the message says
            if re.search(pattern, text):
                return Extraction(Intent.NEEDS_HUMAN, handoff_reason=reason)
        if context.offered_slots and (match := OPTION.search(text)):
            return Extraction(Intent.ACCEPT, option=ORDINALS.get(match.group(1)) or int(match.group(1)))
        preference = _preference(text, context.now.date())
        if preference.is_specific:
            return Extraction(Intent.SCHEDULING, preference)
        if ACCEPT_WORDS.search(text) and (context.proposed_call_at or context.offered_slots):
            return Extraction(Intent.ACCEPT)
        if BOOKING_WORDS.search(text):
            return Extraction(Intent.SCHEDULING)
        return Extraction(Intent.UNCLEAR)


def _preference(text: str, today: date) -> TimePreference:
    earliest = latest = None
    bounds = TIME_BOUND.findall(text)
    for word, hour, minute in bounds:
        if word in ("depois", "a partir"):
            earliest = _time(hour, minute)
        else:
            latest = _time(hour, minute)
    if not bounds:
        if match := AT_TIME.search(text):
            earliest = latest = _time(*match.groups())
        elif match := PART_OF_DAY.search(text):
            earliest, latest = PARTS[match.group(1)]
    return TimePreference(_day(text, today), earliest, latest)


def _day(text: str, today: date) -> date | None:
    if "depois de amanha" in text:
        return today + timedelta(days=2)
    if re.search(r"\bamanha\b", text):
        return today + timedelta(days=1)
    if re.search(r"\bhoje\b", text):
        return today
    if match := WEEKDAY.search(text):  # next occurrence, never today
        return today + timedelta(days=(WEEKDAYS.index(match.group(1)) - today.weekday() - 1) % 7 + 1)
    return None


def _time(hour: str, minute: str | None) -> time | None:
    hour, minute = int(hour), int(minute or 0)
    return time(hour, minute) if hour < 24 and minute < 60 else None
