from datetime import time

import pytest

from reach_agent.clinic_calendar import Calendar, SlotUnavailable
from reach_agent.models import TimePreference
from tests.helpers import SLOTS, TAKEN, fri, mon, thu, tue, wed


@pytest.fixture
def calendar():
    return Calendar(SLOTS, booked=TAKEN)


def test_free_slots_are_future_unbooked_and_in_order(calendar):
    assert calendar.free_slots(after=mon(14, 14)) == [tue(9, 30), tue(11), tue(18, 30)]


def test_booked_slots_are_never_offered(calendar):
    assert wed(10) not in calendar.free_slots(after=mon(0), limit=100)


def test_free_slots_respect_time_preference(calendar):
    after_six = TimePreference(earliest=time(18))
    assert calendar.free_slots(mon(18), after_six) == [tue(18, 30), wed(19), thu(18)]


def test_free_slots_respect_day_preference(calendar):
    friday = TimePreference(day=fri(0).date())
    assert calendar.free_slots(mon(18), friday) == [fri(12), fri(19, 30)]


def test_booking_removes_the_slot(calendar):
    calendar.book(tue(9, 30))
    assert tue(9, 30) not in calendar.free_slots(after=mon(0), limit=100)


def test_cannot_double_book_or_book_unknown_slots(calendar):
    calendar.book(tue(9, 30))
    with pytest.raises(SlotUnavailable):
        calendar.book(tue(9, 30))
    with pytest.raises(SlotUnavailable):
        calendar.book(tue(10, 0))  # not a slot


def test_bundled_calendar_file_loads():
    calendar = Calendar.from_json()
    assert calendar.free_slots(after=mon(14, 14)) == [tue(9, 30), tue(11), tue(18, 30)]
