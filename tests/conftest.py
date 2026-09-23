import os

import pytest

from reach_agent.agent import ReachAgent
from reach_agent.clinic_calendar import Calendar
from reach_agent.extraction import ScriptedExtractor
from reach_agent.llm import PROVIDERS, LLMExtractor
from reach_agent.simulation import Simulation
from tests.helpers import SLOTS, TAKEN, check_invariants, mon


def pytest_addoption(parser):
    parser.addoption("--llm", choices=sorted(PROVIDERS), default=None, metavar="PROVIDER",
                     help=f"also run tests that call a real LLM ({', '.join(PROVIDERS)}); costs credits")


def pytest_collection_modifyitems(config, items):
    provider = config.getoption("--llm")
    if provider and os.environ.get(PROVIDERS[provider].key_env):
        return
    reason = f"needs {PROVIDERS[provider].key_env}" if provider else "calls a real LLM; run with --llm PROVIDER"
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture
def llm_provider(request):
    return request.config.getoption("--llm")


@pytest.fixture(params=["scripted", pytest.param("llm", marks=pytest.mark.llm)])
def simulate(request):
    """Factory: simulate(labels, start) -> a Simulation of one conversation.

    With the scripted extractor, `labels` say what each message means, so the test pins
    down the agent's decisions. With --llm the same scenario also runs end to end with
    the real model, whose readings must lead to the same outcome.
    """
    if request.param == "scripted":
        yield from _checked_simulations(ScriptedExtractor)
        return
    provider = request.config.getoption("--llm")

    def real_llm(labels):  # ignores the labels: the model has to read the messages itself
        return LLMExtractor(provider)

    yield from _checked_simulations(real_llm)


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
