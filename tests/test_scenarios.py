"""End-to-end conversations: the five required cases plus the behaviour around them.

The extractor is scripted, so these tests pin down the agent's *decisions* given a
reading of each message. Whether a real LLM produces those readings is measured
separately (tests/test_eval.py and evals/).
"""

from datetime import time

from reach_agent import messages
from reach_agent.extraction import ExtractionError
from reach_agent.models import Channel, OutboundKind, Phase
from tests.helpers import accept, mon, needs_human, scheduling, thu, tue, wed

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


# -- 4. something that needs human judgement --------------------------------------------

CLINICAL = "Antes de marcar: tenho a gengiva a sangrar desde ontem, é normal?"


def test_clinical_question_hands_off_with_full_context(simulate):
    sim = simulate({ENQUIRY: scheduling(), AFTER_SIX: scheduling(earliest="18:00"),
                    CLINICAL: needs_human("clinical_question")})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.patient(AFTER_SIX, at=mon(14, 40))  # a callback is now pending for 18:00

    [reply] = sim.patient(CLINICAL, at=mon(15))

    assert sim.conv.phase is Phase.HANDED_OFF
    assert reply.text == messages.HANDOFF  # acknowledges, does not try to answer
    assert sim.conv.next_call_at is None   # the pending callback is cancelled
    handoff = sim.conv.handoff
    assert (handoff.reason, handoff.trigger, handoff.at) == ("clinical_question", CLINICAL, mon(15))
    assert handoff.phase_before is Phase.CALLING
    assert handoff.preference.earliest == time(18)
    patient_said = [turn.text for turn in handoff.transcript if turn.speaker == "patient"]
    assert patient_said == [ENQUIRY, AFTER_SIX, CLINICAL]


def test_clinical_enquiry_is_handed_off_before_any_call(simulate):
    enquiry = "Tenho uma dor de dentes muito forte, o que posso tomar?"
    sim = simulate({enquiry: needs_human("clinical_question")})
    outbound = sim.enquiry(enquiry)
    assert sim.conv.phase is Phase.HANDED_OFF
    assert all(out.channel is not Channel.VOICE for out in outbound)


def test_after_handoff_the_agent_stays_silent(simulate):
    sim = simulate({ENQUIRY: scheduling(), "Quero fazer uma reclamação": needs_human("complaint")})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.patient("Quero fazer uma reclamação")
    assert sim.patient("Está aí alguém?") == []  # never even sent to the extractor
    assert sim.conv.transcript[-1].text == "Está aí alguém?"  # but kept for the human


def test_extraction_failure_hands_off_instead_of_guessing(simulate):
    sim = simulate({ENQUIRY: scheduling(), AFTER_SIX: ExtractionError("API timeout")})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.patient(AFTER_SIX)
    assert sim.conv.phase is Phase.HANDED_OFF
    assert sim.conv.handoff.reason == "extraction_failed"
