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


def _real_llm(labels):
    from reach_agent.llm import OpenAIExtractor
    return OpenAIExtractor()  # ignores the labels: the model has to read the messages itself


@pytest.fixture(params=["scripted", pytest.param("openai", marks=pytest.mark.llm)])
def simulate(request):
    """Factory: simulate(labels, start) -> a Simulation of one conversation.

    With the scripted extractor, `labels` say what each message means, so the test pins
    down the agent's decisions. With --llm the same scenario also runs end to end with
    the real model, whose readings must lead to the same outcome.
    """
    yield from _checked_simulations(ScriptedExtractor if request.param == "scripted" else _real_llm)


@pytest.fixture
def simulate_scripted():
    """Same as `simulate`, for tests that need something a real model can't be told to do."""
    yield from _checked_simulations(ScriptedExtractor)


def _checked_simulations(make_extractor):
    """Every simulation created is checked against the safety invariants at the end."""
    created = []

    def factory(labels, start=mon(14, 14)):
        agent = ReachAgent(make_extractor(labels), Calendar(SLOTS, booked=TAKEN))
        created.append(Simulation(agent, start))
        return created[-1]

    yield factory
    for sim in created:
        check_invariants(sim)
