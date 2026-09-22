import pytest

from reach_agent.agent import ReachAgent
from reach_agent.clinic_calendar import Calendar
from reach_agent.extraction import ScriptedExtractor
from reach_agent.simulation import Simulation
from tests.helpers import SLOTS, TAKEN, check_invariants, mon


@pytest.fixture
def simulate():
    """Factory: simulate(labels, start) -> a Simulation whose extractor returns `labels`.

    Every simulation created through it is checked against the safety invariants
    when the test finishes.
    """
    created = []

    def factory(labels, start=mon(14, 14)):
        agent = ReachAgent(ScriptedExtractor(labels), Calendar(SLOTS, booked=TAKEN))
        created.append(Simulation(agent, start))
        return created[-1]

    yield factory
    for sim in created:
        check_invariants(sim)
