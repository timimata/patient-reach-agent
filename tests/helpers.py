"""Shared test vocabulary: a fixed week to live in and short labels for the extractor."""

from datetime import datetime, time

from reach_agent.models import Extraction, Intent, TimePreference


def mon(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 21, hour, minute)  # a Monday


def tue(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 22, hour, minute)


def wed(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 23, hour, minute)


def thu(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 24, hour, minute)


def fri(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 25, hour, minute)


# Same slots as data/calendar.json, spelled out so tests don't depend on the data file.
SLOTS = [mon(16), tue(9, 30), tue(11), tue(18, 30), wed(10), wed(15), wed(19),
         thu(9), thu(18), fri(12), fri(19, 30)]
TAKEN = [mon(16), wed(10)]


# What the extractor "read" in a message. Scenario tests script these so they test the
# agent's decisions; whether a real LLM produces them is measured by the eval.
def scheduling(earliest: str | None = None, latest: str | None = None, day=None) -> Extraction:
    return Extraction(Intent.SCHEDULING, TimePreference(day, _time(earliest), _time(latest)))


def accept(option: int | None = None) -> Extraction:
    return Extraction(Intent.ACCEPT, option=option)


def needs_human(reason: str) -> Extraction:
    return Extraction(Intent.NEEDS_HUMAN, handoff_reason=reason)


def unclear() -> Extraction:
    return Extraction(Intent.UNCLEAR)


def _time(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None
