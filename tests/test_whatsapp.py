"""WhatsApp transport without the network: requests are signed locally with a test token."""

import queue

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from reach_agent.agent import ReachAgent
from reach_agent.clinic_calendar import Calendar
from reach_agent.extraction import ScriptedExtractor
from reach_agent.models import Channel, Conversation, Outbound, OutboundKind, Phase
from reach_agent.whatsapp import InboundMessage, can_send_free_form, create_app
from reach_agent.whatsapp_demo import deliver, run
from tests.helpers import SLOTS, TAKEN, accept, check_invariants, mon, scheduling, tue, wed

TOKEN = "test-auth-token"
URL = "https://example.ngrok-free.app/whatsapp"
PATIENT = "whatsapp:+351910000000"


def form(sid="SM1", body="Olá, queria marcar uma consulta"):
    return {"MessageSid": sid, "From": PATIENT, "ProfileName": "Ana", "Body": body}


def post(client, params, signature=None):
    signature = signature or RequestValidator(TOKEN).compute_signature(URL, params)
    return client.post("/whatsapp", data=params, headers={"X-Twilio-Signature": signature})


@pytest.fixture
def received():
    return []


@pytest.fixture
def client(received):
    return TestClient(create_app(received.append, TOKEN, URL))


def test_signed_message_is_handed_on_and_acknowledged(client, received):
    response = post(client, form())
    assert response.status_code == 200
    assert response.text.endswith("<Response />")  # no inline reply: the agent answers later
    assert received == [InboundMessage("SM1", PATIENT, "Ana", "Olá, queria marcar uma consulta")]


def test_unsigned_or_forged_requests_are_rejected(client, received):
    assert post(client, form(), signature="forged").status_code == 403
    assert client.post("/whatsapp", data=form()).status_code == 403
    assert received == []


def test_signature_covers_the_content(client, received):
    signed_for_other_text = RequestValidator(TOKEN).compute_signature(URL, form(body="outra coisa"))
    assert post(client, form(), signature=signed_for_other_text).status_code == 403


def test_a_retried_message_is_acted_on_once(client, received):
    post(client, form(sid="SM1"))
    post(client, form(sid="SM1"))  # Twilio retrying the same message
    post(client, form(sid="SM2", body="Podem ligar depois das 18h?"))
    assert [message.sid for message in received] == ["SM1", "SM2"]


# -- WhatsApp's 24-hour customer-service window ----------------------------------------------

def conversation_with(*patient_turns):
    conv = Conversation(patient_name="Ana")
    for at, channel in patient_turns:
        conv.say(at, "patient", channel, "...")
    return conv


def test_free_form_is_allowed_within_24h_of_the_patients_last_whatsapp():
    conv = conversation_with((mon(14, 14), Channel.WHATSAPP))
    assert can_send_free_form(conv, mon(14, 20))
    assert can_send_free_form(conv, tue(14, 14))  # exactly 24 h: still inside


def test_free_form_is_blocked_after_24h():
    conv = conversation_with((mon(14, 14), Channel.WHATSAPP))
    assert not can_send_free_form(conv, tue(14, 15))


def test_a_new_patient_message_reopens_the_window():
    conv = conversation_with((mon(14, 14), Channel.WHATSAPP), (tue(20, 0), Channel.WHATSAPP))
    assert can_send_free_form(conv, wed(9, 0))


def test_speaking_on_a_call_does_not_open_the_whatsapp_window():
    conv = conversation_with((mon(18, 0), Channel.VOICE))  # e.g. an enquiry that came by phone
    assert not can_send_free_form(conv, mon(18, 5))


# -- the live demo loop, with a fake Twilio sender -------------------------------------------

ENQUIRY = "Olá, queria marcar uma consulta"
AFTER_SIX = "Estou a trabalhar, podem ligar depois das 18h?"


class FakeSender:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def send(self, to, text):
        if self.error:
            raise self.error
        self.sent.append((to, text))


def events(*items):
    q = queue.Queue()
    for item in (*items, ("terminal", "/sair")):  # /sair last: the loop can never block forever
        q.put(item)
    return q


def whatsapp(sid, text, sender=PATIENT):
    return ("whatsapp", InboundMessage(sid, sender, "Ana", text))


def agent():
    labels = {ENQUIRY: scheduling(), AFTER_SIX: scheduling(earliest="18:00"), "A primeira": accept(option=1)}
    return ReachAgent(ScriptedExtractor(labels), Calendar(SLOTS, booked=TAKEN))


def test_live_demo_books_through_whatsapp_and_a_simulated_call(capsys):
    sender = FakeSender()
    sim = run(events(whatsapp("SM1", ENQUIRY), ("terminal", "n"), whatsapp("SM2", AFTER_SIX),
                     ("terminal", "s"), ("terminal", "A primeira")), agent(), sender, start=mon(14, 14))

    assert sim.conv.phase is Phase.BOOKED and sim.conv.booked_slot == tue(18, 30)
    # only WhatsApp actions reach the phone; the offer and booking happened on the (simulated) call
    assert [to for to, _ in sender.sent] == [PATIENT, PATIENT]
    assert "Tentámos ligar-lhe" in sender.sent[0][1]
    assert sender.sent[1][1] == "Combinado! Ligamos-lhe hoje às 18:00."
    assert "Voz | Agente: Olá Ana" in capsys.readouterr().out
    check_invariants(sim)


def test_live_demo_follows_one_patient_at_a_time(capsys):
    sender = FakeSender()
    sim = run(events(whatsapp("SM1", ENQUIRY), whatsapp("SM2", "Olá!", sender="whatsapp:+351920000000")),
              agent(), sender, start=mon(14, 14))
    assert [turn.text for turn in sim.conv.transcript if turn.speaker == "patient"] == [ENQUIRY]
    assert "ignorado" in capsys.readouterr().out


def test_deliver_refuses_free_form_outside_the_24h_window(capsys):
    conv = conversation_with((mon(14, 14), Channel.WHATSAPP))
    late = Outbound(OutboundKind.OUTREACH, Channel.WHATSAPP, wed(9, 0), "Olá Ana, ...")
    sender = FakeSender()
    deliver([late], conv, PATIENT, sender)
    assert sender.sent == []
    assert conv.events[-1]["event"] == "whatsapp_blocked"
    assert "BLOQUEADO" in capsys.readouterr().out


def test_a_failed_send_is_reported_not_fatal(capsys):
    conv = conversation_with((mon(14, 14), Channel.WHATSAPP))
    message = Outbound(OutboundKind.REPLY, Channel.WHATSAPP, mon(14, 20), "Combinado!")
    deliver([message], conv, PATIENT, FakeSender(error=ConnectionError("no network")))
    assert conv.events[-1]["event"] == "whatsapp_send_failed"
    assert "FALHOU" in capsys.readouterr().out
