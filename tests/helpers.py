"""Shared test vocabulary: a fixed week to live in."""

from datetime import datetime


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
