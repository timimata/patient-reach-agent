from datetime import time

import pytest

from reach_agent.guardrails import ContactPlan, ContactWindow, plan_contact
from reach_agent.models import TimePreference
from tests.helpers import mon, tue

WINDOW = ContactWindow(opens=time(9), closes=time(20))


@pytest.mark.parametrize(
    "moment, allowed",
    [
        (mon(8, 59), False),
        (mon(9, 0), True),   # boundaries are inclusive
        (mon(14, 14), True),
        (mon(20, 0), True),
        (mon(20, 1), False),
        (mon(23, 30), False),
    ],
)
def test_window_boundaries(moment, allowed):
    assert WINDOW.allows(moment) is allowed


@pytest.mark.parametrize(
    "moment, expected",
    [
        (mon(14, 14), mon(14, 14)),  # already allowed: unchanged
        (mon(7, 0), mon(9, 0)),      # too early: later that same morning
        (mon(22, 30), tue(9, 0)),    # too late: next morning
    ],
)
def test_next_allowed(moment, expected):
    assert WINDOW.next_allowed(moment) == expected


def plan(now, day=None, earliest=None, latest=None):
    return plan_contact(TimePreference(day, earliest, latest), now, WINDOW)


def test_preference_inside_window_is_honoured():
    # "podem ligar depois das 18h?" at 14:40
    assert plan(mon(14, 40), earliest=time(18)) == ContactPlan(mon(18), honours_preference=True)


def test_evening_preference_rolls_to_next_morning_and_is_only_a_proposal():
    # "só depois das 21h": nothing in 21h-24h is allowed; nearest allowed not-earlier is 09:00
    assert plan(mon(14, 40), earliest=time(21)) == ContactPlan(tue(9), honours_preference=False)


def test_early_morning_preference_proposes_opening_time():
    # "às 7h30": today's 7h30 has passed, tomorrow's is before opening
    result = plan(mon(14, 40), earliest=time(7, 30), latest=time(7, 30))
    assert result == ContactPlan(tue(9), honours_preference=False)


def test_date_only_preference_uses_opening_time():
    assert plan(mon(14, 40), day=tue(0).date()) == ContactPlan(tue(9), honours_preference=True)


def test_preference_already_passed_today_moves_to_tomorrow():
    # "depois das 18h" said at 20:30: today's window is closed, tomorrow 18:00 honours it
    assert plan(mon(20, 30), earliest=time(18)) == ContactPlan(tue(18), honours_preference=True)


def test_never_plans_in_the_past():
    # "depois das 10h" said at 14:14 means "now is fine"
    assert plan(mon(14, 14), earliest=time(10)) == ContactPlan(mon(14, 14), honours_preference=True)


def test_empty_preference_means_as_soon_as_allowed():
    assert plan(mon(22, 30)) == ContactPlan(tue(9), honours_preference=True)


def test_past_date_is_not_honoured():
    assert plan(tue(10), day=mon(0).date()).honours_preference is False
