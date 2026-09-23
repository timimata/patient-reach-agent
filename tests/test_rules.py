from datetime import date, time

import pytest

from reach_agent.extraction import ExtractionContext
from reach_agent.models import Intent, Phase
from reach_agent.rules import RuleBasedExtractor, normalize
from tests.helpers import mon, thu, tue, wed

WAITING = ExtractionContext(now=mon(14, 14), phase=Phase.AWAITING_REPLY)
PROPOSED = ExtractionContext(now=mon(14, 14), phase=Phase.AWAITING_REPLY, proposed_call_at=tue(9))
OFFERING = ExtractionContext(now=mon(18), phase=Phase.OFFERING_SLOTS, offered_slots=(tue(18, 30), wed(19), thu(18)))


def read(message, context=WAITING):
    return RuleBasedExtractor().extract(message, context)


def test_normalize_strips_accents_and_case():
    assert normalize("  Às 18h, AMANHÃ ") == "as 18h, amanha"


@pytest.mark.parametrize(
    "message, day, earliest, latest",
    [
        ("Podem ligar depois das 18h?", None, time(18), None),
        ("Só consigo antes das 11h", None, None, time(11)),
        ("Pode ser hoje às 16h30?", date(2026, 9, 21), time(16, 30), time(16, 30)),
        ("Amanhã de manhã", date(2026, 9, 22), time(9), time(13)),
        ("Quinta-feira a partir das 15h", date(2026, 9, 24), time(15), None),
        ("Só estou livre depois das 21h", None, time(21), None),  # reported as said; guardrail is elsewhere
    ],
)
def test_time_preferences(message, day, earliest, latest):
    extraction = read(message)
    assert extraction.intent is Intent.SCHEDULING
    preference = extraction.preference
    assert (preference.day, preference.earliest, preference.latest) == (day, earliest, latest)


def test_greeting_is_not_a_time_preference():
    extraction = read("Boa tarde, queria marcar uma consulta")
    assert extraction.intent is Intent.SCHEDULING and not extraction.preference.is_specific


@pytest.mark.parametrize(
    "message, reason",
    [
        ("Tenho dores e febre desde ontem", "clinical_question"),
        ("Depois das 18h. Já agora, é normal ter a cara inchada?", "clinical_question"),
        ("Quero fazer uma reclamação", "complaint"),
        ("Quero cancelar", "other"),
    ],
)
def test_handoff_wins_over_everything_else(message, reason):
    extraction = read(message)
    assert (extraction.intent, extraction.handoff_reason) == (Intent.NEEDS_HUMAN, reason)


def test_picking_an_offered_option():
    assert read("Pode ser a segunda", OFFERING).option == 2
    assert read("A primeira", OFFERING).option == 1


def test_segunda_feira_is_a_day_not_an_option():
    extraction = read("Pode ser na segunda-feira?", OFFERING)
    assert extraction.intent is Intent.SCHEDULING
    assert extraction.preference.day == date(2026, 9, 28)  # next Monday


def test_yes_is_only_accept_when_something_was_proposed():
    assert read("Sim, pode ser", PROPOSED).intent is Intent.ACCEPT
    assert read("Sim, pode ser", WAITING).intent is Intent.UNCLEAR
