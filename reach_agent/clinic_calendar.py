"""A fake clinic calendar: slot start times loaded from JSON, bookings kept in memory.

Bookings are not written back to the file, so every demo run starts from the same state.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import TimePreference

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "calendar.json"


class SlotUnavailable(Exception):
    """The slot does not exist or somebody else already has it."""


class Calendar:
    def __init__(self, slots: list[datetime], booked: list[datetime] = ()):
        self._slots = sorted(slots)
        self._booked = set(booked)

    @classmethod
    def from_json(cls, path: Path = DEFAULT_PATH) -> Calendar:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        slots = [datetime.fromisoformat(slot["start"]) for slot in data["slots"]]
        booked = [datetime.fromisoformat(slot["start"]) for slot in data["slots"] if slot["booked"]]
        return cls(slots, booked)

    def free_slots(
        self, after: datetime, preference: TimePreference = TimePreference(), limit: int = 3
    ) -> list[datetime]:
        """The earliest free slots after `after` that fit the preference."""
        free = (s for s in self._slots if s > after and s not in self._booked)
        return [s for s in free if _fits(s, preference)][:limit]

    def book(self, slot: datetime) -> None:
        if slot not in self._slots or slot in self._booked:
            raise SlotUnavailable(slot)
        self._booked.add(slot)


def _fits(slot: datetime, preference: TimePreference) -> bool:
    return (
        (preference.day is None or slot.date() == preference.day)
        and (preference.earliest is None or slot.time() >= preference.earliest)
        and (preference.latest is None or slot.time() <= preference.latest)
    )
