"""Drives a ReachAgent through time: a simulated clock plus a record of every step.

The terminal demo and the scenario tests both go through this class, so the demo runs
exactly the code path the tests check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .agent import ReachAgent
from .models import Conversation, Outbound, Phase

TYPING_DELAY = timedelta(minutes=5)  # default gap before the patient's next message


@dataclass
class Step:
    at: datetime
    event: str
    phase_before: Phase
    outbound: list[Outbound]


class Simulation:
    def __init__(self, agent: ReachAgent, start: datetime, patient_name: str = "Ana"):
        self.agent = agent
        self.now = start
        self.patient_name = patient_name
        self.conv: Conversation | None = None
        self.steps: list[Step] = []

    @property
    def outbox(self) -> list[Outbound]:
        return [out for step in self.steps for out in step.outbound]

    def enquiry(self, text: str) -> list[Outbound]:
        self.conv, outbound = self.agent.start(self.patient_name, text, self.now)
        return self._record(f"enquiry: {text}", Phase.NEW, outbound)

    def call(self, answered: bool) -> list[Outbound]:
        """The scheduled call happens: the clock jumps to it."""
        self.now = max(self.now, self.conv.next_call_at)
        event = "call answered" if answered else "call not answered"
        return self._run(event, self.agent.on_call_result, answered)

    def patient(self, text: str, at: datetime | None = None) -> list[Outbound]:
        self.now = at or self.now + TYPING_DELAY
        return self._run(f"patient: {text}", self.agent.on_patient_message, text)

    def _run(self, event, handler, *args) -> list[Outbound]:
        phase_before = self.conv.phase
        return self._record(event, phase_before, handler(self.conv, *args, self.now))

    def _record(self, event: str, phase_before: Phase, outbound: list[Outbound]) -> list[Outbound]:
        self.steps.append(Step(self.now, event, phase_before, outbound))
        return outbound
