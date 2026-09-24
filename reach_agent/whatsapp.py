"""Real WhatsApp transport through Twilio: a webhook for messages in, a sender for messages out.

A thin layer around the unchanged agent. The webhook only authenticates the request and
hands the message on, answering Twilio at once; the agent (and its LLM call) runs outside
the request, so a slow model never makes Twilio time out and send the message again.
"""

# No `from __future__ import annotations` here: FastAPI reads the endpoint's annotations at
# runtime, and `Request` is imported inside create_app, where a string annotation can't be resolved.
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Channel, Conversation

EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response />'  # "nothing to reply right now"
FREE_FORM_WINDOW = timedelta(hours=24)  # WhatsApp's customer-service window


def can_send_free_form(conv: Conversation, at: datetime) -> bool:
    """WhatsApp only allows free-form business messages within 24 h of the patient's last
    WhatsApp message; outside that window only pre-approved templates may be sent."""
    last = max((turn.at for turn in conv.transcript
                if turn.speaker == "patient" and turn.channel is Channel.WHATSAPP), default=None)
    return last is not None and at - last <= FREE_FORM_WINDOW


@dataclass(frozen=True)
class InboundMessage:
    sid: str
    sender: str  # the address to reply to: "whatsapp:+3519..." (Twilio) or "3519..." (Meta)
    name: str    # the patient's WhatsApp profile name
    text: str


def create_app(on_message: Callable[[InboundMessage], None], auth_token: str, webhook_url: str):
    """FastAPI app with one endpoint, the URL configured in the Twilio console.

    `webhook_url` must be the exact public URL Twilio posts to (e.g. the ngrok one): Twilio
    signs that URL, not the localhost address this server sees.
    """
    from fastapi import FastAPI, Request, Response
    from twilio.request_validator import RequestValidator

    validator = RequestValidator(auth_token)
    seen: set[str] = set()
    app = FastAPI()

    @app.post("/whatsapp")
    async def whatsapp(request: Request) -> Response:
        params = {key: str(value) for key, value in (await request.form()).items()}
        if not validator.validate(webhook_url, params, request.headers.get("X-Twilio-Signature", "")):
            return Response(status_code=403)  # not signed by Twilio with our token
        sid = params.get("MessageSid", "")
        if sid not in seen:  # Twilio retries on errors: act on each message once
            seen.add(sid)
            on_message(InboundMessage(sid, params.get("From", ""), params.get("ProfileName", ""),
                                      params.get("Body", "")))
        return Response(EMPTY_TWIML, media_type="application/xml")

    return app


class TwilioSender:
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        from twilio.rest import Client  # optional dependency: only for the live WhatsApp demo

        self.client = Client(account_sid, auth_token)
        self.from_number = from_number  # the sandbox number, "whatsapp:+14155238886"

    def send(self, to: str, text: str) -> None:
        self.client.messages.create(to=to, from_=self.from_number, body=text)
