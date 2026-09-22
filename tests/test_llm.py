"""OpenAIExtractor without the network: a fake client stands in for the API."""

import json
from types import SimpleNamespace

import pytest

from reach_agent.extraction import ExtractionContext, ExtractionError
from reach_agent.llm import OpenAIExtractor
from reach_agent.models import Channel, Intent, Phase, Turn
from tests.helpers import mon, thu, tue, wed

OFFERING = ExtractionContext(
    now=mon(18),
    phase=Phase.OFFERING_SLOTS,
    offered_slots=(tue(18, 30), wed(19), thu(18)),
    history=(Turn(mon(14, 40), "patient", Channel.WHATSAPP, "Podem ligar depois das 18h?"),),
)


class FakeCompletions:
    def __init__(self, content=None, error=None):
        self.content, self.error, self.requests = content, error, []

    def create(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(total_tokens=120))


def extractor_returning(content=None, error=None):
    completions = FakeCompletions(content, error)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAIExtractor(model="test-model", client=client), completions


def reading(**fields):
    base = {"intent": "scheduling", "date": None, "earliest": None, "latest": None,
            "option": None, "handoff_reason": None}
    return json.dumps(base | fields)


def test_valid_response_becomes_an_extraction():
    extractor, _ = extractor_returning(reading(intent="accept", option=2))
    extraction = extractor.extract("A de quarta", OFFERING)
    assert (extraction.intent, extraction.option) == (Intent.ACCEPT, 2)
    assert extractor.tokens_used == 120


def test_prompt_carries_the_conversation_context():
    extractor, completions = extractor_returning(reading(intent="accept", option=2))
    extractor.extract("A de quarta", OFFERING)
    request = completions.requests[0]
    system, user = request["messages"]
    assert user == {"role": "user", "content": "A de quarta"}  # patient text kept out of the instructions
    assert "Now: Monday 2026-09-21 18:00" in system["content"]
    assert "2. Wednesday 2026-09-23 19:00" in system["content"]
    assert "Podem ligar depois das 18h?" in system["content"]
    assert request["model"] == "test-model"
    assert request["response_format"]["json_schema"]["strict"] is True


@pytest.mark.parametrize(
    "content, error",
    [
        (None, ConnectionError("network down")),
        ("this is not json", None),
        (reading(intent="book_it"), None),     # valid JSON, invalid reading
        (reading(earliest="6pm"), None),
    ],
)
def test_anything_unexpected_raises_extraction_error(content, error):
    extractor, _ = extractor_returning(content, error)
    with pytest.raises(ExtractionError):
        extractor.extract("Olá", OFFERING)


def test_option_outside_the_offer_is_dropped():
    extractor, _ = extractor_returning(reading(intent="accept", option=7))
    assert extractor.extract("A sétima", OFFERING).option is None


@pytest.mark.llm
def test_real_api_smoke():
    """One real call, only with --llm: checks the key, model and schema are accepted."""
    extraction = OpenAIExtractor().extract("Podem ligar depois das 18h?", OFFERING)
    assert extraction.intent is Intent.SCHEDULING
