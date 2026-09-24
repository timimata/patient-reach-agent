"""Real WhatsApp transport through Meta's WhatsApp Cloud API: the same job as the Twilio one.

Twilio trial accounts may only send Twilio's pre-approved templates, so the agent's free-text
replies were refused (error 21654). Meta's own API lets its test number reply with free text
within the 24-hour window, which is all this demo needs. Same shape as the Twilio adapter:
the webhook authenticates the request, hands text messages on and answers at once.
"""

# No `from __future__ import annotations`: FastAPI reads the endpoints' annotations at runtime.
import hashlib
import hmac
import json
from collections.abc import Callable

from .whatsapp import InboundMessage

GRAPH_API = "https://graph.facebook.com/v23.0"


def is_signed(body: bytes, signature: str, app_secret: str) -> bool:
    """Meta signs each notification: "sha256=" + HMAC-SHA256 of the raw body, keyed with the App Secret."""
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def text_messages(payload: dict) -> list[InboundMessage]:
    """The text messages in a notification. Delivery statuses and non-text messages are skipped."""
    found = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {contact.get("wa_id"): contact.get("profile", {}).get("name", "")
                     for contact in value.get("contacts", [])}
            for message in value.get("messages", []):
                if message.get("type") == "text":
                    sender = message.get("from", "")  # "351910000000": digits, no "+"
                    found.append(InboundMessage(message.get("id", ""), sender, names.get(sender, ""),
                                                message.get("text", {}).get("body", "")))
    return found


def create_app(on_message: Callable[[InboundMessage], None], app_secret: str, verify_token: str):
    """FastAPI app for the Callback URL set in the Meta App Dashboard (WhatsApp > Configuration)."""
    from fastapi import FastAPI, Request, Response

    seen: set[str] = set()
    app = FastAPI()

    @app.get("/whatsapp")
    async def verify(request: Request) -> Response:
        """Meta checks the URL once, when it is saved: echo the challenge if the token is ours."""
        query = request.query_params
        if query.get("hub.mode") == "subscribe" and query.get("hub.verify_token") == verify_token:
            return Response(query.get("hub.challenge", ""), media_type="text/plain")
        return Response(status_code=403)

    @app.post("/whatsapp")
    async def notify(request: Request) -> Response:
        body = await request.body()
        if not is_signed(body, request.headers.get("X-Hub-Signature-256", ""), app_secret):
            return Response(status_code=403)  # not signed by Meta with our App Secret
        for message in text_messages(json.loads(body)):
            if message.sid not in seen:  # Meta retries on errors: act on each message once
                seen.add(message.sid)
                on_message(message)
        return Response(status_code=200)

    return app


class MetaSender:
    def __init__(self, access_token: str, phone_number_id: str, client=None):
        import httpx

        self.url = f"{GRAPH_API}/{phone_number_id}/messages"
        self.client = client or httpx.Client(timeout=10)
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def send(self, to: str, text: str) -> None:
        response = self.client.post(self.url, headers=self.headers, json={
            "messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}})
        if response.is_error:  # keep Meta's explanation (expired token, number not allowed, ...)
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
