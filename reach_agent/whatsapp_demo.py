"""Live demo on real WhatsApp: the patient writes from a phone, calls stay simulated here.

    python -m reach_agent.whatsapp_demo [--via meta|twilio] [--llm deepseek] [--port 8000]

Each channel has its own transport. WhatsApp messages travel through Meta or Twilio to and from
the patient's phone; the voice call is simulated in this terminal (you pick up, and type
what the patient says on the call). The agent is the same one the tests check, on the same
simulated clock as the terminal demo. One patient at a time, state in memory.
"""

from __future__ import annotations

import argparse
import os
import queue
import threading
from datetime import datetime

from .agent import ReachAgent
from .cli import DEMO_START, make_extractor, print_outcome, print_state, show, stamp
from .clinic_calendar import Calendar
from .llm import PROVIDERS
from .models import Channel, Conversation, Outbound, Phase
from .simulation import Simulation
from .whatsapp import can_send_free_form

ENV = {  # what each WhatsApp provider needs, read from the environment so no secret is in the code
    "meta": ("META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID", "META_APP_SECRET", "META_VERIFY_TOKEN"),
    "twilio": ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "WHATSAPP_WEBHOOK_URL"),
}


def run(events: queue.Queue, agent: ReachAgent, sender, start: datetime = DEMO_START) -> Simulation | None:
    """Drive one conversation from ("whatsapp", InboundMessage) and ("terminal", line) events."""
    sim: Simulation | None = None
    patient = ""
    print("À espera de uma mensagem de WhatsApp no número da demo...")
    while sim is None or not sim.conv.phase.is_terminal:
        kind, payload = _next(events)
        if kind == "terminal" and payload.strip() == "/sair":
            break
        if kind == "whatsapp":
            if sim is None:
                sim, patient = Simulation(agent, start, patient_name=payload.name or "paciente"), payload.sender
            elif payload.sender != patient:
                print(f"(ignorado: {payload.sender}; esta demo segue um paciente de cada vez)")
                continue
            elif sim.conv.channel is Channel.VOICE:
                print("(mensagem de WhatsApp durante a chamada: ignorada na demo)")
                continue
            print(f"{stamp(sim.now)} WhatsApp <- {patient}: {payload.text}")
            outbound = sim.enquiry(payload.text) if sim.conv is None else sim.patient(payload.text)
        else:
            outbound = _terminal_step(sim, payload.strip())
            if outbound is None:
                continue
        deliver(outbound, sim.conv, patient, sender)
        _prompt(sim.conv)
    if sim is not None:
        print_outcome(sim.conv)
    return sim


def _next(events: queue.Queue):
    """Wait for the next event in short slices: on Windows a plain get() can't be interrupted by Ctrl+C."""
    while True:
        try:
            return events.get(timeout=0.5)
        except queue.Empty:
            continue


def deliver(outbound: list[Outbound], conv: Conversation, patient: str, sender) -> None:
    """Route each action to its channel's transport: WhatsApp to the phone, voice to this terminal."""
    for out in outbound:
        if out.channel is not Channel.WHATSAPP:
            show([out])
            continue
        if not can_send_free_form(conv, out.at):
            conv.log(out.at, "whatsapp_blocked", reason="outside the 24 h window", text=out.text)
            print(f"{stamp(out.at)} WhatsApp BLOQUEADO: fora da janela de 24 h (precisaria de um template aprovado)")
            continue
        try:
            sender.send(patient, out.text)
        except Exception as exc:  # network, credentials, the provider refusing: report it, keep the demo alive
            conv.log(out.at, "whatsapp_send_failed", error=str(exc))
            print(f"{stamp(out.at)} WhatsApp FALHOU: {exc}")
            continue
        print(f"{stamp(out.at)} WhatsApp -> {patient}: {out.text}")


def _terminal_step(sim: Simulation | None, line: str) -> list[Outbound] | None:
    if sim is None:
        print("(ainda não há conversa: manda primeiro uma mensagem de WhatsApp)")
        return None
    if line == "/estado":
        print_state(sim.conv)
        return None
    if sim.conv.phase is Phase.CALLING:
        if line.lower() in ("s", "n"):
            return sim.call(answered=line.lower() == "s")
        print("(responde s ou n)")
        return None
    if sim.conv.channel is Channel.VOICE:  # on the call: you speak as the patient
        return sim.patient(line) if line else None
    if line == "/sem-resposta" and sim.conv.phase is Phase.AWAITING_REPLY:
        return sim.no_reply()
    print("(o paciente responde pelo WhatsApp; aqui: /sem-resposta, /estado, /sair)")
    return None


def _prompt(conv: Conversation) -> None:
    if conv.phase is Phase.CALLING:
        print(f"{stamp(conv.next_call_at)} O agente liga ao paciente. Atender? (s/n)")
    elif conv.phase is Phase.OFFERING_SLOTS:
        print("Paciente (voz)> escreve aqui o que o paciente diz na chamada")
    elif conv.phase is Phase.AWAITING_REPLY:
        print("(à espera de resposta no WhatsApp; /sem-resposta se o paciente não responder)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Demo com WhatsApp real; chamadas simuladas no terminal.")
    parser.add_argument("--via", choices=sorted(ENV), default="meta", help="fornecedor de WhatsApp (default: meta)")
    parser.add_argument("--llm", choices=sorted(PROVIDERS), metavar="PROVIDER",
                        help=f"usar um LLM ({', '.join(PROVIDERS)}) em vez das regras")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    missing = [name for name in ENV[args.via] if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Faltam variáveis de ambiente: {', '.join(missing)} (ver README).")
    settings = [os.environ[name].strip() for name in ENV[args.via]]  # a pasted token often ends in a space

    events: queue.Queue = queue.Queue()
    app, sender = _transport(args.via, settings, lambda message: events.put(("whatsapp", message)))
    _serve(app, args.port)
    threading.Thread(target=_read_terminal, args=(events,), daemon=True).start()
    print(f"Webhook ({args.via}) em http://127.0.0.1:{args.port}/whatsapp")
    agent = ReachAgent(make_extractor(args.llm), Calendar.from_json())
    run(events, agent, sender)


def _transport(via: str, settings: list[str], on_message):
    """The webhook app and the sender for one WhatsApp provider."""
    if via == "meta":
        from .whatsapp_meta import MetaSender, create_app

        access_token, phone_number_id, app_secret, verify_token = settings
        return create_app(on_message, app_secret, verify_token), MetaSender(access_token, phone_number_id)
    from .whatsapp import TwilioSender, create_app

    account_sid, auth_token, from_number, webhook_url = settings
    return create_app(on_message, auth_token, webhook_url), TwilioSender(account_sid, auth_token, from_number)


def _serve(app, port: int) -> None:
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()


def _read_terminal(events: queue.Queue) -> None:
    while True:
        try:
            line = input()
        except EOFError:
            events.put(("terminal", "/sair"))
            return
        events.put(("terminal", line))


if __name__ == "__main__":
    main()
