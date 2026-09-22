"""End-to-end conversations: the five required cases plus the behaviour around them.

The extractor is scripted, so these tests pin down the agent's *decisions* given a
reading of each message. Whether a real LLM produces those readings is measured
separately (tests/test_eval.py and evals/).
"""

from reach_agent.models import Channel, OutboundKind, Phase
from tests.helpers import accept, mon, scheduling, thu, tue, wed

ENQUIRY = "Olá, queria marcar uma consulta"
AFTER_SIX = "Estou a trabalhar. Podem ligar depois das 18h?"


# -- 1. clear booking request (the flow shown on getwilco.ai) ---------------------------

def test_clear_request_is_booked_after_missed_call_and_callback(simulate):
    sim = simulate({ENQUIRY: scheduling(), AFTER_SIX: scheduling(earliest="18:00"), "A primeira": accept(option=1)})

    [call] = sim.enquiry(ENQUIRY)
    assert (call.channel, call.at) == (Channel.VOICE, mon(14, 14))

    [follow_up] = sim.call(answered=False)
    assert (follow_up.channel, follow_up.kind) == (Channel.WHATSAPP, OutboundKind.OUTREACH)
    assert sim.conv.phase is Phase.AWAITING_REPLY

    confirmation, callback = sim.patient(AFTER_SIX, at=mon(14, 40))
    assert "hoje às 18:00" in confirmation.text
    assert (callback.channel, callback.at) == (Channel.VOICE, mon(18))

    [offer] = sim.call(answered=True)
    assert offer.channel is Channel.VOICE
    # memory: "depois das 18h" said on WhatsApp still shapes what is offered on the call
    assert sim.conv.offered_slots == [tue(18, 30), wed(19), thu(18)]

    [booked] = sim.patient("A primeira")
    assert sim.conv.phase is Phase.BOOKED
    assert sim.conv.booked_slot == tue(18, 30)
    assert "amanhã às 18:30" in booked.text
    assert tue(18, 30) not in sim.agent.calendar.free_slots(after=mon(0), limit=100)
