"""Terminal demo: you play the patient, the agent runs on a simulated clock.

    python -m reach_agent                  # offline, rule-based extractor
    python -m reach_agent --llm deepseek   # real LLM (needs DEEPSEEK_API_KEY; see llm.PROVIDERS)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from .agent import ReachAgent
from .clinic_calendar import Calendar
from .llm import PROVIDERS, LLMExtractor
from .models import Channel, Conversation, Outbound, OutboundKind, Phase
from .simulation import Simulation

DEMO_START = datetime(2026, 9, 21, 14, 14)  # a Monday, matching data/calendar.json
DEFAULT_ENQUIRY = "Olá, queria marcar uma consulta"
WEEKDAYS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
HELP = "Comandos: /sem-resposta (o paciente não responde)  /estado  /trace  /sair"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Simulação do agente Reach no terminal.")
    parser.add_argument("--llm", choices=sorted(PROVIDERS), metavar="PROVIDER",
                        help=f"usar um LLM ({', '.join(PROVIDERS)}) em vez das regras")
    parser.add_argument("--name", default="Ana", help="nome do paciente")
    args = parser.parse_args(argv)

    extractor = _make_extractor(args.llm)
    agent = ReachAgent(extractor, Calendar.from_json())
    sim = Simulation(agent, DEMO_START, patient_name=args.name)
    window = agent.window
    print(f"Relógio simulado: {_stamp(DEMO_START)} | contacto permitido "
          f"{window.opens:%H:%M}-{window.closes:%H:%M} | extractor: {extractor.name}")
    print(HELP)

    enquiry = _ask(f"\nEnquiry do paciente [{DEFAULT_ENQUIRY}]> ")
    if enquiry is None:
        return
    _show(sim.enquiry(enquiry or DEFAULT_ENQUIRY))

    while not sim.conv.phase.is_terminal:
        if sim.conv.phase is Phase.CALLING:
            answer = _ask(f"{_stamp(sim.conv.next_call_at)} O agente liga ao paciente. Atender? (s/n)> ")
            if answer is None:
                break
            _show(sim.call(answered=answer.strip().lower().startswith("s")))
            continue
        line = _ask("Paciente> ")
        if line is None or line.strip() == "/sair":
            break
        line = line.strip()
        if line == "/sem-resposta":
            if sim.conv.phase is Phase.AWAITING_REPLY:
                _show(sim.no_reply())
            else:
                print("  (só faz sentido quando o agente está à espera de resposta por WhatsApp)")
        elif line == "/estado":
            _print_state(sim.conv)
        elif line == "/trace":
            _print_json(sim.conv.events)
        elif line:
            _show(sim.patient(line))

    _print_outcome(sim.conv)


def _make_extractor(provider: str | None):
    if provider is None:
        from .rules import RuleBasedExtractor
        return RuleBasedExtractor()
    try:
        return LLMExtractor(provider)
    except Exception as exc:  # missing package or API key
        raise SystemExit(f"Não foi possível usar o LLM ({exc}). Define {PROVIDERS[provider].key_env} "
                         "ou corre sem --llm.")


def _show(outbound: list[Outbound]) -> None:
    for out in outbound:
        if out.channel is Channel.VOICE and out.kind is OutboundKind.OUTREACH:
            print(f"{_stamp(out.at)} [chamada agendada]")
            continue
        label = "Voz" if out.channel is Channel.VOICE else "WhatsApp"
        text = out.text.replace("\n", "\n" + " " * 8)
        print(f"{_stamp(out.at)} {label} | Agente: {text}")


def _print_state(conv: Conversation) -> None:
    print(f"  fase: {conv.phase.value} | canal: {conv.channel.value} | sem resposta seguidas: {conv.unanswered}"
          f" | clarificações: {conv.clarifications}")
    print(f"  preferência lembrada: {conv.preference}")
    print(f"  próxima chamada: {conv.next_call_at} | proposta pendente: {conv.proposed_call_at}")


def _print_outcome(conv: Conversation | None) -> None:
    if conv is None:
        return
    print()
    if conv.phase is Phase.BOOKED:
        print(f"Resultado: consulta marcada para {_stamp(conv.booked_slot)}")
    elif conv.phase is Phase.HANDED_OFF:
        handoff = conv.handoff
        print(f"Resultado: passado a um humano (motivo: {handoff.reason}). Registo do handoff:")
        _print_json({
            "reason": handoff.reason,
            "at": handoff.at,
            "trigger": handoff.trigger,
            "phase_before": handoff.phase_before.value,
            "preference": handoff.preference,
            "transcript": [f"{_stamp(t.at)} {t.speaker}/{t.channel.value}: {t.text}" for t in handoff.transcript],
        })
    else:
        print(f"Simulação interrompida na fase {conv.phase.value}.")


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _ask(prompt: str) -> str | None:
    try:
        return input(prompt)
    except EOFError:
        return None


def _stamp(moment: datetime) -> str:
    return f"[{WEEKDAYS[moment.weekday()]} {moment:%d/%m %H:%M}]"
