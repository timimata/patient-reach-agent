"""End-to-end conversations: the five required cases plus the behaviour around them.

The extractor is scripted, so these tests pin down the agent's *decisions* given a
reading of each message. Whether a real LLM produces those readings is measured
separately (tests/test_eval.py and evals/).
"""

from datetime import time

from reach_agent import messages
from reach_agent.extraction import ExtractionError
from reach_agent.models import Channel, OutboundKind, Phase
from tests.helpers import accept, fri, mon, needs_human, scheduling, thu, tue, unclear, wed

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


# -- 2. ambiguous time preference --------------------------------------------------------

def test_ambiguous_preference_asks_for_clarification_then_continues(simulate):
    sim = simulate({ENQUIRY: scheduling(), "Liguem mais logo": scheduling(),
                    "Às 17h": scheduling(earliest="17:00", latest="17:00")})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)

    [question] = sim.patient("Liguem mais logo")
    assert "A que horas prefere" in question.text
    assert sim.conv.phase is Phase.AWAITING_REPLY and sim.conv.next_call_at is None  # no guessing

    confirmation, callback = sim.patient("Às 17h")
    assert callback.at == mon(17)
    # it continued the same conversation instead of starting over
    assert sim.conv.clarifications == 1
    assert sum("Tentámos ligar-lhe" in turn.text for turn in sim.conv.transcript) == 1


def test_repeated_confusion_is_handed_off_after_two_questions(simulate):
    sim = simulate({ENQUIRY: scheduling(), "hmm": unclear(), "não sei": unclear(), "talvez": unclear()})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.patient("hmm")
    sim.patient("não sei")
    assert sim.conv.phase is Phase.AWAITING_REPLY

    [reply] = sim.patient("talvez")
    assert sim.conv.phase is Phase.HANDED_OFF
    assert (sim.conv.handoff.reason, sim.conv.handoff.trigger) == ("patient_not_understood", "talvez")
    assert reply.text == messages.HANDOFF


def test_unclear_slot_choice_asks_which_option(simulate):
    sim = simulate({ENQUIRY: scheduling(), "Sim": accept(), "A segunda": accept(option=2)})
    sim.enquiry(ENQUIRY)
    sim.call(answered=True)
    [question] = sim.patient("Sim")  # yes... to which of the three?
    assert "qual destas opções" in question.text and sim.conv.phase is Phase.OFFERING_SLOTS
    sim.patient("A segunda")
    assert sim.conv.booked_slot == sim.conv.offered_slots[1]


# -- 3. preference outside the allowed contact hours --------------------------------------

AFTER_NINE_PM = "Só estou livre depois das 21h"


def test_out_of_hours_preference_is_not_used_and_nearest_valid_time_is_proposed(simulate):
    sim = simulate({ENQUIRY: scheduling(), AFTER_NINE_PM: scheduling(earliest="21:00"),
                    "Sim, pode ser": accept()})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)

    [proposal] = sim.patient(AFTER_NINE_PM, at=mon(14, 40))
    assert sim.conv.next_call_at is None  # nothing scheduled at 21h, nor anywhere else yet
    assert sim.conv.proposed_call_at == tue(9)
    assert "entre as 09:00 e as 20:00" in proposal.text and "amanhã às 09:00" in proposal.text

    # "sim" only means something because the agent remembers what it proposed
    confirmation, callback = sim.patient("Sim, pode ser")
    assert callback.at == tue(9)
    assert sim.conv.proposed_call_at is None


def test_patient_can_counter_propose_a_valid_time(simulate):
    sim = simulate({ENQUIRY: scheduling(), AFTER_NINE_PM: scheduling(earliest="21:00"),
                    "Então às 19h30": scheduling(earliest="19:30", latest="19:30")})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.patient(AFTER_NINE_PM, at=mon(14, 40))
    confirmation, callback = sim.patient("Então às 19h30")
    assert callback.at == mon(19, 30)


def test_enquiry_arriving_at_night_is_first_called_next_morning(simulate):
    sim = simulate({ENQUIRY: scheduling()}, start=mon(22, 30))
    [call] = sim.enquiry(ENQUIRY)
    assert (call.channel, call.at) == (Channel.VOICE, tue(9))


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


# -- 5. no response / timeout ---------------------------------------------------------------

def test_no_response_follows_up_within_hours_then_stops_for_human_review(simulate):
    sim = simulate({ENQUIRY: scheduling()}, start=mon(19, 30))
    sim.enquiry(ENQUIRY)

    [follow_up] = sim.call(answered=False)  # attempt 1 at 19:30
    assert follow_up.at == mon(19, 30)

    [reminder] = sim.no_reply()             # attempt 2 times out at 23:30...
    assert reminder.at == tue(9)            # ...but the reminder waits for the window

    assert sim.no_reply() == []             # attempt 3: stop contacting
    assert sim.conv.phase is Phase.HANDED_OFF
    assert sim.conv.handoff.reason == "contact_attempts_exhausted"
    assert [out.channel for out in sim.outbox] == [Channel.VOICE, Channel.WHATSAPP, Channel.WHATSAPP]


def test_any_reply_resets_the_unanswered_count(simulate):
    sim = simulate({ENQUIRY: scheduling(), AFTER_SIX: scheduling(earliest="18:00")})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.patient(AFTER_SIX, at=mon(14, 40))
    sim.call(answered=False)  # missed the agreed callback too
    assert sim.conv.unanswered == 1  # consecutive, not total: the patient did answer in between
    assert sim.conv.phase is Phase.AWAITING_REPLY


# -- conversation memory: adapt and continue, never start over ------------------------------

def test_extractor_reads_each_message_with_the_conversation_as_context(simulate):
    sim = simulate({ENQUIRY: scheduling(), AFTER_SIX: scheduling(earliest="18:00"),
                    "A de quarta": accept(option=2)})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.patient(AFTER_SIX, at=mon(14, 40))
    sim.call(answered=True)
    sim.patient("A de quarta")

    message, context = sim.agent.extractor.calls[-1]
    assert message == "A de quarta"
    assert context.phase is Phase.OFFERING_SLOTS
    assert context.offered_slots == (tue(18, 30), wed(19), thu(18))  # what "quarta" refers to
    assert AFTER_SIX in [turn.text for turn in context.history]
    assert sim.conv.booked_slot == wed(19)


def test_pending_callback_can_be_rescheduled(simulate):
    sim = simulate({ENQUIRY: scheduling(), AFTER_SIX: scheduling(earliest="18:00"),
                    "Afinal só consigo às 19h": scheduling(earliest="19:00", latest="19:00")})
    sim.enquiry(ENQUIRY)
    sim.call(answered=False)
    sim.patient(AFTER_SIX, at=mon(14, 40))
    assert sim.conv.next_call_at == mon(18)

    confirmation, callback = sim.patient("Afinal só consigo às 19h", at=mon(16))
    assert sim.conv.next_call_at == callback.at == mon(19)


def test_new_preference_during_the_call_reoffers_matching_slots(simulate):
    sim = simulate({ENQUIRY: scheduling(), "Nenhuma dá. Tem na sexta?": scheduling(day=fri(0).date()),
                    "A segunda": accept(option=2)})
    sim.enquiry(ENQUIRY)
    sim.call(answered=True)
    sim.patient("Nenhuma dá. Tem na sexta?")
    assert sim.conv.offered_slots == [fri(12), fri(19, 30)]
    sim.patient("A segunda")  # "the second" of the *new* offer
    assert sim.conv.booked_slot == fri(19, 30)


def test_slot_taken_meanwhile_is_reoffered_not_double_booked(simulate):
    sim = simulate({ENQUIRY: scheduling(), "A primeira": accept(option=1)})
    sim.enquiry(ENQUIRY)
    sim.call(answered=True)
    first = sim.conv.offered_slots[0]
    sim.agent.calendar.book(first)  # another patient, on another line, was faster

    [reoffer] = sim.patient("A primeira")
    assert sim.conv.phase is Phase.OFFERING_SLOTS
    assert first not in sim.conv.offered_slots
    assert reoffer.text.startswith(messages.SLOT_TAKEN)


def test_no_free_slots_hands_off(simulate):
    sim = simulate({ENQUIRY: scheduling()})
    for slot in sim.agent.calendar.free_slots(after=mon(0), limit=100):
        sim.agent.calendar.book(slot)
    sim.enquiry(ENQUIRY)
    sim.call(answered=True)
    assert sim.conv.handoff.reason == "no_availability"
