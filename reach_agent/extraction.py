"""The pluggable "understanding" step: patient text -> Extraction.

The agent depends only on the `Extractor` protocol, so the same agent code runs with the
real LLM, the offline rule-based baseline, or a scripted oracle in the tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Protocol

from .models import Extraction, Intent, Phase, TimePreference, Turn

# Shared by the LLM prompt and the rule-based extractor so both mean the same thing.
PARTS_OF_DAY = {
    "manhã": (time(9), time(13)),
    "tarde": (time(13), time(19)),
    "noite": (time(19), time(23)),
}


@dataclass(frozen=True)
class ExtractionContext:
    """What the extractor may know besides the message: the relevant conversation memory."""

    now: datetime
    phase: Phase
    offered_slots: tuple[datetime, ...] = ()
    proposed_call_at: datetime | None = None
    history: tuple[Turn, ...] = ()


class ExtractionError(Exception):
    """No trustworthy reading (API down, invalid JSON, ...). The agent hands off."""


class Extractor(Protocol):
    name: str

    def extract(self, message: str, context: ExtractionContext) -> Extraction: ...


class ScriptedExtractor:
    """Test double: returns hand-written labels and records every call it receives."""

    name = "scripted"

    def __init__(self, labels: dict[str, Extraction | ExtractionError]):
        self.labels = labels
        self.calls: list[tuple[str, ExtractionContext]] = []

    def extract(self, message: str, context: ExtractionContext) -> Extraction:
        self.calls.append((message, context))
        label = self.labels[message]  # KeyError here means a test forgot to label a message
        if isinstance(label, ExtractionError):
            raise label
        return label


def parse_extraction(data: dict, n_options: int = 0) -> Extraction:
    """Validate a JSON-like reading (LLM output or dataset label) into an Extraction."""
    try:
        intent = Intent(data["intent"])
        preference = TimePreference(
            day=_parse(date.fromisoformat, data.get("date")),
            earliest=_parse(time.fromisoformat, data.get("earliest")),
            latest=_parse(time.fromisoformat, data.get("latest")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExtractionError(f"invalid extraction {data!r}: {exc}") from exc
    if (preference.earliest is not None and preference.latest is not None
            and preference.earliest > preference.latest):
        raise ExtractionError(f"earliest after latest in {data!r}")
    option = data.get("option")
    if not (isinstance(option, int) and 1 <= option <= n_options):
        option = None  # not one of the options we offered: treat it as "didn't say"
    return Extraction(intent, preference, option, data.get("handoff_reason"))


def extraction_to_dict(extraction: Extraction) -> dict:
    """Inverse of parse_extraction; used for the trace and for comparing in the eval."""
    preference = extraction.preference
    return {
        "intent": extraction.intent.value,
        "date": preference.day.isoformat() if preference.day else None,
        "earliest": preference.earliest.isoformat("minutes") if preference.earliest else None,
        "latest": preference.latest.isoformat("minutes") if preference.latest else None,
        "option": extraction.option,
        "handoff_reason": extraction.handoff_reason,
    }


def _parse(parser, value):
    return None if value is None else parser(value)
