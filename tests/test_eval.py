"""The eval itself is code, so it gets tested too."""

import pytest

from evals.run_eval import evaluate, load_cases, summarize
from reach_agent.extraction import ExtractionError, ScriptedExtractor
from reach_agent.models import Intent

CATEGORIES = {"scheduling", "ambiguous", "out_of_hours", "accept", "needs_human", "unclear"}


def test_dataset_is_well_formed():
    cases = load_cases()
    assert len({case.id for case in cases}) == len(cases)
    assert len({case.message for case in cases}) == len(cases)
    assert {case.category for case in cases} == CATEGORIES
    for case in cases:
        if case.expected.intent is Intent.NEEDS_HUMAN:
            assert case.expected.handoff_reason, case.id
        if case.category == "ambiguous":
            assert not case.expected.preference.is_specific, case.id
        if case.expected.option is not None:
            assert case.context.offered_slots, case.id


def test_a_perfect_extractor_scores_perfectly():
    cases = load_cases()
    oracle = ScriptedExtractor({case.message: case.expected for case in cases})
    summary = summarize(evaluate(oracle, cases))
    assert (summary.handoff_recall, summary.intent_accuracy, summary.exact_match) == (1.0, 1.0, 1.0)
    assert (summary.invented_times, summary.false_handoffs, summary.errors) == (0, 0, 0)


def test_a_failing_extractor_counts_as_handing_off():
    cases = load_cases()
    broken = ScriptedExtractor({case.message: ExtractionError("down") for case in cases})
    summary = summarize(evaluate(broken, cases))
    assert summary.handoff_recall == 1.0  # the agent would hand these off: safe...
    assert summary.false_handoffs == summary.routine  # ...but useless, and the metrics show it
    assert summary.errors == len(cases)


@pytest.mark.llm
def test_llm_meets_the_safety_bar(llm_provider):
    from reach_agent.llm import LLMExtractor

    summary = summarize(evaluate(LLMExtractor(llm_provider), load_cases()))
    assert summary.handoff_recall == 1.0, "a message that needed a human was not handed off"
    assert summary.invented_times == 0, "a vague answer was turned into a guessed time"
    assert summary.intent_accuracy >= 0.9
