"""Everything the agent says to patients, in one place.

Fixed templates, not generated text: the clinic can proof-read every sentence, tests can
assert on them, and the LLM can never promise something the code did not decide.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .guardrails import ContactWindow

CLINIC = "Clínica Exemplo"
WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")

HANDOFF = (
    "Obrigado pela sua mensagem. Vou passar o seu pedido a um membro da nossa equipa, "
    "que entrará em contacto consigo. Se for urgente, ligue para o SNS 24 (808 24 24 24) "
    "ou, numa emergência, para o 112."
)
SLOT_TAKEN = "Entretanto essa vaga foi ocupada. "


def when(moment: datetime, now: datetime) -> str:
    """'hoje às 18:00', 'amanhã às 09:00' or 'quinta, 24/09, às 10:00'."""
    if moment.date() == now.date():
        day = "hoje"
    elif moment.date() == (now + timedelta(days=1)).date():
        day = "amanhã"
    else:
        day = f"{WEEKDAYS[moment.weekday()]}, {moment:%d/%m},"
    return f"{day} às {moment:%H:%M}"


def missed_call(name: str) -> str:
    return (f"Olá {name}, daqui fala a assistente da {CLINIC}. Tentámos ligar-lhe por causa do "
            "seu pedido de marcação. A que horas lhe dá jeito que voltemos a ligar?")


def reminder(name: str) -> str:
    return (f"Olá {name}, continuamos disponíveis para marcar a sua consulta. "
            "Quando lhe dá jeito falarmos?")


def call_confirmed(at: datetime, now: datetime) -> str:
    return f"Combinado! Ligamos-lhe {when(at, now)}."


def propose_call(at: datetime, window: ContactWindow, now: datetime) -> str:
    return (f"Só podemos contactar entre as {window.opens:%H:%M} e as {window.closes:%H:%M}. "
            f"Podemos ligar-lhe {when(at, now)}?")


def ask_call_time(window: ContactWindow) -> str:
    return ("Desculpe, não percebi bem. A que horas prefere que liguemos? Pode ser entre as "
            f"{window.opens:%H:%M} e as {window.closes:%H:%M}, por exemplo \"amanhã depois das 18h\".")


def greeting(name: str) -> str:
    return f"Olá {name}, daqui fala a assistente da {CLINIC}. "


def offer_slots(slots: list[datetime], now: datetime, *, opening: str = "", matched: bool = True) -> str:
    lead = ("Tenho estas vagas para a sua consulta:" if matched
            else "Não tenho vagas no horário que indicou. As mais próximas são:")
    return f"{opening}{lead}\n{_numbered(slots, now)}\nQual prefere?"


def ask_which_slot(slots: list[datetime], now: datetime) -> str:
    return f"Desculpe, qual destas opções prefere?\n{_numbered(slots, now)}"


def booked(slot: datetime, now: datetime) -> str:
    return f"Ficou marcada a sua consulta para {when(slot, now)}. Até lá!"


def _numbered(slots: list[datetime], now: datetime) -> str:
    return "\n".join(f"{number}) {when(slot, now)}" for number, slot in enumerate(slots, 1))
