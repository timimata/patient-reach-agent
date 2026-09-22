"""Contact-hours guardrail.

Deliberately plain code, not a prompt instruction: the rule has to hold even when the
LLM misreads a message, so the LLM never decides *when* a patient is contacted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class ContactWindow:
    opens: time = time(9, 0)
    closes: time = time(20, 0)

    def allows(self, moment: datetime) -> bool:
        return self.opens <= moment.time() <= self.closes

    def next_allowed(self, moment: datetime) -> datetime:
        """`moment` itself if allowed, otherwise the next time the window opens."""
        if self.allows(moment):
            return moment
        day = moment.date() if moment.time() < self.opens else moment.date() + timedelta(days=1)
        return datetime.combine(day, self.opens)
