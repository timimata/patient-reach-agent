"""Score extractors against the labelled dataset in evals/dataset.jsonl.

    python -m evals.run_eval                 # rule-based baseline only (free, offline)
    python -m evals.run_eval rules deepseek  # side by side; needs DEEPSEEK_API_KEY
                                             # (providers: see reach_agent/llm.py)
    python -m evals.run_eval rules deepseek --dataset holdout

Two datasets. dataset.jsonl ("dev") is the one the prompt and the rules were tuned on, so
scores there are optimistic. holdout.jsonl was written and committed after that tuning,
before its first run, and must never be used to change the prompt or the rules: it is
the honest estimate.

Metrics, in the order they matter for this product:
  handoff recall   every message that needs a human gets one (safety: must be 100%)
  invented times   vague answers must stay vague, not become a guessed time
  intent accuracy  and exact match (intent + the fields the agent acts on for that intent)
  false handoffs   routine messages escalated for nothing (costs staff time, not safety)
An extractor error counts as a handoff, because that is what the agent does with it.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter

from reach_agent.extraction import (ExtractionContext, ExtractionError, Extractor,
                                    extraction_to_dict, parse_extraction)
from reach_agent.models import Extraction, Intent, Phase

DATASETS = {
    "dev": Path(__file__).with_name("dataset.jsonl"),
    "holdout": Path(__file__).with_name("holdout.jsonl"),
}
NOW = datetime(2026, 9, 21, 14, 14)  # every case is read as if it arrived at this moment (a Monday)
# The fields agent.py actually reads for each intent. Anything else the extractor fills in
# (e.g. the time of the option the patient picked) changes nothing, so it is not an error.
ACTED_ON = {
    Intent.SCHEDULING: ("date", "earliest", "latest"),
    Intent.ACCEPT: ("option",),
    Intent.NEEDS_HUMAN: (),
    Intent.UNCLEAR: (),
}


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    message: str
    context: ExtractionContext
    expected: Extraction


@dataclass(frozen=True)
class Result:
    case: Case
    actual: Extraction | None  # None: the extractor raised
    error: str | None
    ms: float

    @property
    def handed_off(self) -> bool:
        return self.actual is None or self.actual.intent is Intent.NEEDS_HUMAN

    @property
    def intent_ok(self) -> bool:
        return self.actual is not None and self.actual.intent is self.case.expected.intent

    @property
    def exact(self) -> bool:
        return self.actual is not None and compared(self.actual) == compared(self.case.expected)


@dataclass(frozen=True)
class Summary:
    cases: int
    handoff_recall: float
    invented_times: int
    ambiguous: int
    intent_accuracy: float
    exact_match: float
    false_handoffs: int
    routine: int
    errors: int
    mean_ms: float


def load_cases(path: Path = DATASETS["dev"]) -> list[Case]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        offered = tuple(datetime.fromisoformat(slot) for slot in raw.get("offered_slots", []))
        proposal = raw.get("proposed_call_at")
        context = ExtractionContext(
            now=NOW,
            phase=Phase(raw["phase"]),
            offered_slots=offered,
            proposed_call_at=datetime.fromisoformat(proposal) if proposal else None,
        )
        expected = parse_extraction(raw["expected"], n_options=len(offered))
        cases.append(Case(raw["id"], raw["category"], raw["message"], context, expected))
    return cases


def evaluate(extractor: Extractor, cases: list[Case]) -> list[Result]:
    results = []
    for case in cases:
        started = perf_counter()
        try:
            actual, error = extractor.extract(case.message, case.context), None
        except ExtractionError as exc:
            actual, error = None, str(exc)
        results.append(Result(case, actual, error, (perf_counter() - started) * 1000))
    return results


def summarize(results: list[Result]) -> Summary:
    needs_human = [r for r in results if r.case.expected.intent is Intent.NEEDS_HUMAN]
    routine = [r for r in results if r.case.expected.intent is not Intent.NEEDS_HUMAN]
    ambiguous = [r for r in results if r.case.category == "ambiguous"]
    return Summary(
        cases=len(results),
        handoff_recall=_share([r.handed_off for r in needs_human]),
        invented_times=sum(r.actual is not None and r.actual.preference.is_specific for r in ambiguous),
        ambiguous=len(ambiguous),
        intent_accuracy=_share([r.intent_ok for r in results]),
        exact_match=_share([r.exact for r in results]),
        false_handoffs=sum(r.handed_off for r in routine),
        routine=len(routine),
        errors=sum(r.error is not None for r in results),
        mean_ms=sum(r.ms for r in results) / len(results),
    )


def compared(extraction: Extraction) -> dict:
    data = extraction_to_dict(extraction)
    return {"intent": data["intent"], **{field: data[field] for field in ACTED_ON[extraction.intent]}}


ROWS = (
    ("handoff recall", lambda s: f"{s.handoff_recall:.0%}"),
    ("invented times", lambda s: f"{s.invented_times}/{s.ambiguous}"),
    ("intent accuracy", lambda s: f"{s.intent_accuracy:.0%}"),
    ("exact match", lambda s: f"{s.exact_match:.0%}"),
    ("false handoffs", lambda s: f"{s.false_handoffs}/{s.routine}"),
    ("errors", lambda s: str(s.errors)),
    ("mean latency", lambda s: f"{s.mean_ms:.0f} ms"),
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare extractors on the labelled dataset.")
    parser.add_argument("extractors", nargs="*", default=["rules"],
                        help="rules and/or LLM providers from reach_agent/llm.py")
    parser.add_argument("--dataset", choices=DATASETS, default="dev")
    args = parser.parse_args(argv)
    names = args.extractors

    cases = load_cases(DATASETS[args.dataset])
    extractors = {name: _make(name) for name in names}
    runs = {name: evaluate(extractor, cases) for name, extractor in extractors.items()}
    summaries = [summarize(results) for results in runs.values()]

    print(f"{args.dataset}: {len(cases)} labelled cases, read as if received {NOW:%Y-%m-%d %H:%M}\n")
    widths = [max(12, len(name) + 2) for name in names]
    print(f"{'':18}" + "".join(f"{name:>{w}}" for name, w in zip(names, widths, strict=True)))
    for label, show in ROWS:
        print(f"{label:18}" + "".join(f"{show(s):>{w}}" for s, w in zip(summaries, widths, strict=True)))

    for name, results in runs.items():
        misses = [r for r in results if not r.exact]
        print(f"\n{name}: {len(misses)} of {len(results)} not exactly right")
        for r in misses:
            got = r.error or _brief(compared(r.actual))
            print(f"  {r.case.id:30} expected {_brief(compared(r.case.expected))}")
            print(f"  {'':30} got      {got}")
        tokens = getattr(extractors[name], "tokens_used", 0)
        if tokens:
            print(f"  ({tokens} tokens used)")


def _make(name: str) -> Extractor:
    if name == "rules":
        from reach_agent.rules import RuleBasedExtractor
        return RuleBasedExtractor()
    from reach_agent.llm import PROVIDERS, LLMExtractor
    if name in PROVIDERS:
        return LLMExtractor(name)
    raise SystemExit(f"unknown extractor {name!r}; use rules and/or {', '.join(PROVIDERS)}")


def _share(flags: list[bool]) -> float:
    return sum(flags) / len(flags) if flags else 1.0


def _brief(data: dict) -> str:
    return ", ".join(f"{key}={value}" for key, value in data.items() if value is not None)


if __name__ == "__main__":
    main()
