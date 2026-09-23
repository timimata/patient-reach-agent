"""WhatsApp transport without the network: requests are signed locally with a test token."""

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from reach_agent.whatsapp import InboundMessage, create_app

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
