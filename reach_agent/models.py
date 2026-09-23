"""Domain types shared by the agent, the calendar, the extractors and the tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum


class Channel(str, Enum):
    VOICE = "voice"
    WHATSAPP = "whatsapp"


class Phase(str, Enum):
    NEW = "new"                        # enquiry received, nothing done yet
    CALLING = "calling"                # a call is scheduled
    AWAITING_REPLY = "awaiting_reply"  # we messaged the patient and wait for an answer
    OFFERING_SLOTS = "offering_slots"  # patient is on the line, choosing a slot
    BOOKED = "booked"
    HANDED_OFF = "handed_off"          # a human owns the conversation from here

    @property
    def is_terminal(self) -> bool:
        return self in (Phase.BOOKED, Phase.HANDED_OFF)


class Intent(str, Enum):
    SCHEDULING = "scheduling"    # wants to book and/or says when they are available
    ACCEPT = "accept"            # agrees to what the agent proposed / picks an option
    NEEDS_HUMAN = "needs_human"  # clinical question, complaint, anything non-routine
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class TimePreference:
    """What the patient said about *when*. None means "not said", never "any"."""

    day: date | None = None
    earliest: time | None = None
    latest: time | None = None

    @property
    def is_specific(self) -> bool:
        return any(value is not None for value in (self.day, self.earliest, self.latest))

    def admits(self, moment: datetime) -> bool:
        """Whether `moment` is consistent with everything the patient said."""
        return (
            (self.day is None or moment.date() == self.day)
            and (self.earliest is None or moment.time() >= self.earliest)
            and (self.latest is None or moment.time() <= self.latest)
        )


@dataclass(frozen=True)
class Extraction:
    """Structured reading of one patient message: the only thing the LLM produces."""

    intent: Intent
    preference: TimePreference = field(default_factory=TimePreference)
    option: int | None = None  # 1-based index into the slots we offered
    handoff_reason: str | None = None


class OutboundKind(str, Enum):
    OUTREACH = "outreach"  # agent-initiated contact: must respect the contact window
    REPLY = "reply"        # immediate answer to something the patient just said


@dataclass(frozen=True)
class Outbound:
    """Something the agent does towards the patient. On VOICE it is a scheduled call."""

    kind: OutboundKind
    channel: Channel
    at: datetime
    text: str


@dataclass(frozen=True)
class Turn:
    at: datetime
    speaker: str  # "patient" | "agent" | "system"
    channel: Channel
    text: str


@dataclass(frozen=True)
class Handoff:
    """Everything a human needs to pick the conversation up without re-asking."""

    reason: str
    at: datetime
    trigger: str | None  # the patient message that caused it, if any
    phase_before: Phase
    preference: TimePreference
    transcript: tuple[Turn, ...]


@dataclass
class Conversation:
    """The agent's memory of one patient. Every event handler reads and updates it."""

    patient_name: str
    phase: Phase = Phase.NEW
    channel: Channel = Channel.WHATSAPP  # where the patient is talking to us right now
    preference: TimePreference = field(default_factory=TimePreference)
    next_call_at: datetime | None = None
    proposed_call_at: datetime | None = None  # proposed by us, waiting for the patient's OK
    offered_slots: list[datetime] = field(default_factory=list)
    unanswered: int = 0      # consecutive contact attempts without an answer
    clarifications: int = 0  # questions asked because we did not understand
    booked_slot: datetime | None = None
    handoff: Handoff | None = None
    transcript: list[Turn] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)  # instrumentation trace

    def say(self, at: datetime, speaker: str, channel: Channel, text: str) -> None:
        self.transcript.append(Turn(at, speaker, channel, text))

    def log(self, moment: datetime, event: str, **data) -> None:
        self.events.append({"time": moment, "event": event, **data})
