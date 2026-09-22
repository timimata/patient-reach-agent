import pytest

from reach_agent.agent import ReachAgent
from reach_agent.clinic_calendar import Calendar
from reach_agent.extraction import ScriptedExtractor
from reach_agent.simulation import Simulation
from tests.helpers import SLOTS, TAKEN, mon


@pytest.fixture
def simulate():
    """Factory: simulate(labels, start) -> a Simulation whose extractor returns `labels`."""

    def factory(labels, start=mon(14, 14)):
        agent = ReachAgent(ScriptedExtractor(labels), Calendar(SLOTS, booked=TAKEN))
        return Simulation(agent, start)

    return factory
