from datetime import date, time

import pytest

from reach_agent.extraction import ExtractionError, extraction_to_dict, parse_extraction
from reach_agent.models import Intent


def test_parses_a_complete_reading():
    extraction = parse_extraction(
        {"intent": "scheduling", "date": "2026-09-22", "earliest": "18:00", "latest": None,
         "option": None, "handoff_reason": None}
    )
    assert extraction.intent is Intent.SCHEDULING
    assert extraction.preference.day == date(2026, 9, 22)
    assert extraction.preference.earliest == time(18)
    assert extraction.preference.latest is None


def test_missing_optional_fields_mean_not_said():
    extraction = parse_extraction({"intent": "unclear"})
    assert not extraction.preference.is_specific and extraction.option is None


@pytest.mark.parametrize(
    "data",
    [
        {"intent": "book_now"},                          # not an intent we know
        {},                                              # no intent at all
        {"intent": "scheduling", "earliest": "18h"},     # not HH:MM
        {"intent": "scheduling", "date": "amanhã"},      # not ISO
        {"intent": "scheduling", "earliest": "19:00", "latest": "09:00"},  # inverted window
    ],
)
def test_invalid_readings_raise(data):
    with pytest.raises(ExtractionError):
        parse_extraction(data)


@pytest.mark.parametrize("option, n_options, expected", [(2, 3, 2), (4, 3, None), (0, 3, None), (1, 0, None)])
def test_option_must_point_at_something_we_offered(option, n_options, expected):
    assert parse_extraction({"intent": "accept", "option": option}, n_options).option == expected


def test_round_trip():
    data = {"intent": "scheduling", "date": "2026-09-24", "earliest": "15:00", "latest": "15:30",
            "option": None, "handoff_reason": None}
    assert extraction_to_dict(parse_extraction(data)) == data
