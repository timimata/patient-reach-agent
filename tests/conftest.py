import os

import pytest

from reach_agent.agent import ReachAgent
from reach_agent.clinic_calendar import Calendar
from reach_agent.extraction import ScriptedExtractor
from reach_agent.simulation import Simulation
from tests.helpers import SLOTS, TAKEN, check_invariants, mon


def pytest_addoption(parser):
    parser.addoption("--llm", action="store_true", help="also run tests that call the OpenAI API (costs credits)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--llm") and os.environ.get("OPENAI_API_KEY"):
        return
    reason = "needs OPENAI_API_KEY" if config.getoption("--llm") else "calls the OpenAI API; run with --llm"
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(pytest.mark.skip(reason=reason))


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
