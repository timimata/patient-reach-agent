"""Meta WhatsApp Cloud API transport without the network: notifications signed with a test secret."""

import hashlib
import hmac
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from reach_agent.whatsapp import InboundMessage
from reach_agent.whatsapp_meta import GRAPH_API, MetaSender, create_app, text_messages

SECRET = "test-app-secret"
VERIFY = "test-verify-token"
PATIENT = "351910000000"


def notification(*messages, name="Ana"):
    """The shape Meta posts for incoming messages (entry > changes > value)."""
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": "123"},
             "contacts": [{"profile": {"name": name}, "wa_id": PATIENT}], "messages": list(messages)}
    return {"object": "whatsapp_business_account",
            "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": value}]}]}


def text(mid="wamid.1", body="Olá, queria marcar uma consulta"):
    return {"from": PATIENT, "id": mid, "timestamp": "1790000000", "type": "text", "text": {"body": body}}


def sign(body: bytes, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post(client, payload, signature=None):
    body = json.dumps(payload).encode()
    return client.post("/whatsapp", content=body, headers={"X-Hub-Signature-256": signature or sign(body)})


@pytest.fixture
def received():
    return []


@pytest.fixture
def client(received):
    return TestClient(create_app(received.append, SECRET, VERIFY))


def test_meta_verifies_the_url_with_our_token(client):
    params = {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "1158201444"}
    response = client.get("/whatsapp", params=params)
    assert response.status_code == 200 and response.text == "1158201444"


def test_url_verification_with_another_token_is_refused(client):
    params = {"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "1"}
    assert client.get("/whatsapp", params=params).status_code == 403


def test_signed_text_message_is_handed_on(client, received):
    assert post(client, notification(text())).status_code == 200
    assert received == [InboundMessage("wamid.1", PATIENT, "Ana", "Olá, queria marcar uma consulta")]


def test_unsigned_or_forged_notifications_are_rejected(client, received):
    assert post(client, notification(text()), signature="sha256=forged").status_code == 403
    assert client.post("/whatsapp", json=notification(text())).status_code == 403
    body = json.dumps(notification(text())).encode()
    assert post(client, notification(text()), signature=sign(body, secret="another-app")).status_code == 403
    assert received == []


def test_signature_covers_the_content(client, received):
    signed_for_other_text = sign(json.dumps(notification(text(body="outra coisa"))).encode())
    assert post(client, notification(text()), signature=signed_for_other_text).status_code == 403


def test_a_retried_message_is_acted_on_once(client, received):
    post(client, notification(text(mid="wamid.1")))
    post(client, notification(text(mid="wamid.1")))  # Meta retrying the same message
    post(client, notification(text(mid="wamid.2", body="Podem ligar depois das 18h?")))
    assert [message.sid for message in received] == ["wamid.1", "wamid.2"]


def test_delivery_statuses_and_non_text_messages_are_skipped():
    statuses = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.9", "status": "read"}]}}]}]}
    image = {"from": PATIENT, "id": "wamid.3", "type": "image", "image": {"id": "media-1"}}
    assert text_messages(statuses) == []
    assert text_messages(notification(image, text(mid="wamid.4", body="Olá"))) == [
        InboundMessage("wamid.4", PATIENT, "Ana", "Olá")]


# -- sending, against a fake Graph API ---------------------------------------------------------

def fake_graph(status=200, reply=None):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=reply or {"messages": [{"id": "wamid.out"}]})

    return requests, httpx.Client(transport=httpx.MockTransport(handler))


def test_sender_posts_free_text_to_the_phone_number():
    requests, client = fake_graph()
    MetaSender("token-123", "PHONE_ID", client=client).send(PATIENT, "Combinado! Ligamos-lhe hoje às 18:00.")
    [request] = requests
    assert str(request.url) == f"{GRAPH_API}/PHONE_ID/messages"
    assert request.headers["Authorization"] == "Bearer token-123"
    assert json.loads(request.content) == {"messaging_product": "whatsapp", "to": PATIENT, "type": "text",
                                           "text": {"body": "Combinado! Ligamos-lhe hoje às 18:00."}}


def test_a_refused_send_raises_with_metas_reason():
    error = {"error": {"message": "Recipient phone number not in allowed list", "code": 131030}}
    _, client = fake_graph(status=400, reply=error)
    with pytest.raises(RuntimeError, match="131030"):
        MetaSender("token-123", "PHONE_ID", client=client).send(PATIENT, "Olá")
