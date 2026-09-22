"""The Reach agent: turns an enquiry into a booked appointment, or a clean handoff.

An explicit state machine (see `Phase`). The extractor (LLM) only *reads* what the
patient wrote; every decision (when to contact, what to offer, when to stop and bring
in a human) is plain code here, so it is testable without an LLM and cannot be talked
around by a cleverly worded message.
"""

from __future__ import annotations

from datetime import datetime
from time import perf_counter

from . import messages
from .clinic_calendar import Calendar
from .extraction import ExtractionContext, Extractor, extraction_to_dict
from .guardrails import ContactWindow, plan_contact
from .models import Channel, Conversation, Extraction, Intent, Outbound, OutboundKind, Phase

OFFER_SIZE = 3     # slots offered at once
HISTORY_TURNS = 6  # recent turns the extractor gets as context


class ReachAgent:
    def __init__(self, extractor: Extractor, calendar: Calendar, window: ContactWindow | None = None):
        self.extractor = extractor
        self.calendar = calendar
        self.window = window or ContactWindow()

    # -- events: the only public API ---------------------------------------------------

    def start(self, patient_name: str, enquiry: str, now: datetime) -> tuple[Conversation, list[Outbound]]:
        """A new enquiry arrives: read it, then plan the first call."""
        conv = Conversation(patient_name=patient_name)
        conv.say(now, "patient", conv.channel, enquiry)
        extraction = self._read(conv, enquiry, now)
        if extraction.intent is Intent.SCHEDULING:
            conv.preference = extraction.preference
        plan = plan_contact(conv.preference, now, self.window)
        return conv, [self._schedule_call(conv, plan.at, now)]

    def on_call_result(self, conv: Conversation, answered: bool, now: datetime) -> list[Outbound]:
        """The scheduled call happened; the patient picked up or not."""
        self._expect(conv, Phase.CALLING)
        conv.next_call_at = None
        if not answered:
            conv.say(now, "system", Channel.VOICE, "[chamada não atendida]")
            return self._no_answer(conv, now, messages.missed_call(conv.patient_name))
        conv.say(now, "system", Channel.VOICE, "[chamada atendida]")
        conv.channel = Channel.VOICE
        return self._offer_slots(conv, now, opening=messages.greeting(conv.patient_name))

    def on_patient_message(self, conv: Conversation, text: str, now: datetime) -> list[Outbound]:
        conv.say(now, "patient", conv.channel, text)
        extraction = self._read(conv, text, now)
        if conv.phase is Phase.OFFERING_SLOTS:
            return self._on_slot_answer(conv, extraction, now)
        return self._on_call_time_answer(conv, extraction, now)

    # -- decisions ------------------------------------------------------------------------

    def _on_call_time_answer(self, conv: Conversation, extraction: Extraction, now: datetime) -> list[Outbound]:
        """AWAITING_REPLY or CALLING: the patient is telling us when to call."""
        if extraction.intent is Intent.SCHEDULING and extraction.preference.is_specific:
            conv.preference = extraction.preference
            plan = plan_contact(extraction.preference, now, self.window)
            if plan.honours_preference:
                return self._confirm_call(conv, plan.at, now)
        raise NotImplementedError(f"not handled yet: {extraction}")

    def _on_slot_answer(self, conv: Conversation, extraction: Extraction, now: datetime) -> list[Outbound]:
        """OFFERING_SLOTS: the patient is choosing one of conv.offered_slots."""
        if extraction.intent is Intent.ACCEPT:
            option = extraction.option or (1 if len(conv.offered_slots) == 1 else None)
            if option is not None and 1 <= option <= len(conv.offered_slots):
                return self._book(conv, conv.offered_slots[option - 1], now)
        raise NotImplementedError(f"not handled yet: {extraction}")

    # -- actions --------------------------------------------------------------------------

    def _confirm_call(self, conv: Conversation, at: datetime, now: datetime) -> list[Outbound]:
        conv.proposed_call_at = None
        call = self._schedule_call(conv, at, now)
        return [self._reply(conv, messages.call_confirmed(call.at, now), now), call]

    def _schedule_call(self, conv: Conversation, at: datetime, now: datetime) -> Outbound:
        at = self._within_contact_hours(conv, max(at, now))
        conv.phase = Phase.CALLING
        conv.next_call_at = at
        conv.log(now, "call_scheduled", at=at)
        return Outbound(OutboundKind.OUTREACH, Channel.VOICE, at, f"Chamada para {conv.patient_name}")

    def _no_answer(self, conv: Conversation, now: datetime, follow_up: str) -> list[Outbound]:
        """A contact attempt went unanswered: follow up on the other channel."""
        conv.phase = Phase.AWAITING_REPLY
        conv.channel = Channel.WHATSAPP
        at = self._within_contact_hours(conv, now)
        conv.say(at, "agent", Channel.WHATSAPP, follow_up)
        return [Outbound(OutboundKind.OUTREACH, Channel.WHATSAPP, at, follow_up)]

    def _offer_slots(self, conv: Conversation, now: datetime, opening: str = "") -> list[Outbound]:
        # The remembered preference ("depois das 18h") also hints which slots will suit.
        preferred = self.calendar.free_slots(after=now, preference=conv.preference, limit=OFFER_SIZE)
        slots = preferred or self.calendar.free_slots(after=now, limit=OFFER_SIZE)
        conv.phase = Phase.OFFERING_SLOTS
        conv.offered_slots = slots
        conv.log(now, "slots_offered", slots=slots, matched_preference=bool(preferred))
        text = messages.offer_slots(slots, now, opening=opening, matched=bool(preferred))
        return [self._reply(conv, text, now)]

    def _book(self, conv: Conversation, slot: datetime, now: datetime) -> list[Outbound]:
        self.calendar.book(slot)
        conv.phase = Phase.BOOKED
        conv.booked_slot = slot
        conv.log(now, "booked", slot=slot)
        return [self._reply(conv, messages.booked(slot, now), now)]

    # -- plumbing -------------------------------------------------------------------------

    def _read(self, conv: Conversation, text: str, now: datetime) -> Extraction:
        """Ask the extractor what the message means, with the conversation as context."""
        context = ExtractionContext(
            now=now,
            phase=conv.phase,
            offered_slots=tuple(conv.offered_slots),
            proposed_call_at=conv.proposed_call_at,
            history=tuple(conv.transcript[-HISTORY_TURNS - 1:-1]),  # excludes `text` itself
        )
        started = perf_counter()
        extraction = self.extractor.extract(text, context)
        conv.log(now, "extraction", extractor=self.extractor.name, message=text,
                 result=extraction_to_dict(extraction), ms=round((perf_counter() - started) * 1000, 1))
        return extraction

    def _reply(self, conv: Conversation, text: str, now: datetime) -> Outbound:
        conv.say(now, "agent", conv.channel, text)
        return Outbound(OutboundKind.REPLY, conv.channel, now, text)

    def _within_contact_hours(self, conv: Conversation, desired: datetime) -> datetime:
        """The single choke point for agent-initiated contact, so the guardrail can't be skipped."""
        at = self.window.next_allowed(desired)
        if at != desired:
            conv.log(desired, "guardrail_deferred", requested=desired, at=at)
        return at

    @staticmethod
    def _expect(conv: Conversation, phase: Phase) -> None:
        if conv.phase is not phase:
            raise ValueError(f"event only valid in {phase.value}; conversation is {conv.phase.value}")
