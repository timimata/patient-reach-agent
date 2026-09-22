from datetime import time

import pytest

from reach_agent.guardrails import ContactWindow
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
