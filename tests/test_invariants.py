"""Checks on the checks: an invariant that can never fail proves nothing."""

import pytest

from reach_agent.agent import ReachAgent
from reach_agent.clinic_calendar import Calendar
from reach_agent.extraction import ScriptedExtractor
from reach_agent.simulation import Simulation
from tests.helpers import SLOTS, TAKEN, check_invariants, mon, scheduling

ENQUIRY = "Olá, queria marcar uma consulta"


def no_response_at_night():
    sim = Simulation(ReachAgent(ScriptedExtractor({ENQUIRY: scheduling()}), Calendar(SLOTS, TAKEN)), mon(19, 30))
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.no_reply()  # times out at 23:30
    return sim


def test_invariants_hold_with_the_guardrail_in_place():
    check_invariants(no_response_at_night())


def test_invariants_catch_a_disabled_guardrail(monkeypatch):
    monkeypatch.setattr(ReachAgent, "_within_contact_hours", lambda self, conv, desired: desired)
    with pytest.raises(AssertionError, match="outside contact hours"):
        check_invariants(no_response_at_night())  # the reminder now goes out at 23:30
