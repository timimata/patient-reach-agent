"""Contact-hours guardrail.

Deliberately plain code, not a prompt instruction: the rule has to hold even when the
LLM misreads a message, so the LLM never decides *when* a patient is contacted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .models import TimePreference


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


@dataclass(frozen=True)
class ContactPlan:
    at: datetime
    honours_preference: bool  # False: `at` is only a proposal, the patient must agree first


def plan_contact(
    preference: TimePreference, now: datetime, window: ContactWindow, horizon_days: int = 7
) -> ContactPlan:
    """Earliest moment that satisfies both the patient's preference and the contact window.

    If no such moment exists (e.g. "call me after 21h"), fall back to the nearest allowed
    moment that is not earlier than what the patient asked for, flagged as not honouring
    the preference: the agent proposes it instead of silently using it.
    """
    if preference.day is not None:
        days = [preference.day]
    else:  # no day given: the stated hours apply to any upcoming day
        days = [now.date() + timedelta(days=offset) for offset in range(horizon_days)]

    fallback = None
    for day in days:
        start = max(datetime.combine(day, preference.earliest or time.min), now)
        end = datetime.combine(day, preference.latest or time.max)
        if start > end:
            continue  # that day's preferred window is already over
        at = window.next_allowed(start)
        if at <= end:
            return ContactPlan(at, honours_preference=True)
        fallback = fallback or at
    return ContactPlan(fallback or window.next_allowed(now), honours_preference=False)
