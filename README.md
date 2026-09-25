# patient-reach-agent

[![tests](https://github.com/timimata/patient-reach-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/timimata/patient-reach-agent/actions/workflows/tests.yml)

To prepare for my interview at Wilco, I built a simplified, tested version of the kind of problem
Wilco solves: the **Reach** phase, turning a patient's enquiry into a booked appointment. The goal is
to show how I think about it. It is not a replica of the product: only the decision logic, in text,
with no real telephony, and most of the effort went into testing it properly.

**In 30 seconds**

- **What:** Wilco's Reach flow as a tested simulation: enquiry → missed call → WhatsApp → callback →
  booked, with contact-hour guardrails and human handoff.
- **Design:** the LLM only *reads* messages into validated JSON; every decision is plain, tested code.
- **Headline result:** on 21 held-out messages, a regex baseline sent **40%** of the messages that
  needed a human to one; the LLM (DeepSeek) sent **100%**, in each of 5 runs, at a p95 of ~1 s per
  message.
- **Also:** an optional adapter connects the same agent to real WhatsApp (Meta's Cloud API or
  Twilio) without changing the agent. Tested live: a real phone went from "Olá" to a booking.
- **Run:** `pip install -r requirements.txt`, then `pytest` (offline, under a second) and
  `python -m reach_agent` (terminal demo).

```
[seg 21/09 14:14] [chamada agendada]
[seg 21/09 14:14] O agente liga ao paciente. Atender? (s/n)> n
[seg 21/09 14:14] WhatsApp | Agente: Olá Ana, daqui fala a assistente da Clínica Exemplo. Tentámos ligar-lhe [...]
Paciente> Estou a trabalhar, podem ligar depois das 18h?
[seg 21/09 14:19] WhatsApp | Agente: Combinado! Ligamos-lhe hoje às 18:00.
[seg 21/09 18:00] [chamada agendada]
[seg 21/09 18:00] O agente liga ao paciente. Atender? (s/n)> s
[seg 21/09 18:00] Voz | Agente: Olá Ana, [...] Tenho estas vagas para a sua consulta:
        1) amanhã às 18:30
        2) quarta, 23/09, às 19:00
        3) quinta, 24/09, às 18:00
Paciente> a primeira
[seg 21/09 18:05] Voz | Agente: Ficou marcada a sua consulta para amanhã às 18:30. Até lá!
```

The simulated clinic is Portuguese, so everything the patient sees is in Portuguese. In English:
missed call → WhatsApp asking when to call back → *"I'm at work, can you call after 6 pm?"* →
callback at 18:00 → three slots offered → *"the first one"* → booked.

## How this maps to Wilco's Reach flow

The flow follows the example Wilco shows on [getwilco.ai](https://getwilco.ai):

| On Wilco's site | In this project |
|---|---|
| *Call 09:15: no answer. The enquiry stays open.* | `ReachAgent.start()` schedules the call; `on_call_result(answered=False)` |
| *WhatsApp 09:17: sent a message to find a better time* | `_no_answer()` sends the WhatsApp message |
| *"I'm at work. Could you call after six?"* | the extractor (LLM) reads the message and returns `scheduling, earliest=18:00` |
| *Flow updated: call back at 18:30* | `plan_contact()` intersects the preference with the 09:00–20:00 window: callback at 18:00 |
| *Callback: spoke with the patient and booked the visit* | `_offer_slots()` (slots from `data/calendar.json`, filtered by the remembered preference), then `_book()` |
| *Strict calling-hour limits* | `ContactWindow` + `_within_contact_hours()`, the single point every agent-initiated contact goes through |
| *Bring in your team at contact limits or clinical questions* | `_hand_off()`: clinical question, complaint, 3 unanswered attempts, message not understood, LLM failure |

```
 enquiry ─► CALLING ──answered──► OFFERING_SLOTS ──picks one──► BOOKED
             │   ▲                    └─ "tem na sexta?" (any on Friday?) ─► offers again
   not answered  │ time agreed
             ▼   │
        AWAITING_REPLY ──3 consecutive unanswered contacts──► HANDED_OFF
 (in any phase: clinical / complaint / not understood 3x / LLM error ─► HANDED_OFF)
```

## Design decisions

1. **The LLM only reads; the code decides.** The LLM turns free text into an `Extraction` (intent,
   date, times, chosen option) as JSON, and that JSON is always validated in code before use. *When*
   to call, what to offer and when to stop is deterministic code in `agent.py`. So the logic is
   testable without an LLM, and no cleverly worded message can talk the agent into breaking a rule.
   Because validation lives in code, switching providers is only configuration: OpenAI enforces the
   schema server-side, DeepSeek only guarantees valid JSON, and nothing else changes.
2. **The guardrail is code, in one place.** Every agent-initiated contact (calls, follow-ups,
   reminders) goes through `_within_contact_hours()`. A preference outside the window
   ("só depois das 21h", *only after 9 pm*) is never used: the agent explains and *proposes* the
   nearest valid time that is not earlier than requested, and schedules only once the patient
   agrees. Immediate replies to a patient's message are not agent-initiated contact, so the window
   does not apply to them.
3. **When in doubt, a human.** If the LLM fails (network, invalid JSON), the message goes to a human;
   nothing is guessed. On handoff the agent records the reason, the message that caused it, the
   phase, the preference and the full transcript, cancels any pending callback and stops replying.
4. **Explicit memory.** `Conversation` holds the stated preference, the pending proposal, the offered
   slots and the counters. That is what lets a "sim" (*yes*) mean "yes to the 09:00 proposal", and
   "a de quarta" (*the Wednesday one*) point at the right slot. This memory is passed to the extractor
   as context.
5. **Template replies** (`messages.py`), not generated ones: the clinic can review every sentence and
   tests can check them. The price is that they sound rigid (see limitations).

## Scope: what was left out and why

- **No real telephony.** What I wanted to show is the decision logic and how to test it; the calls
  are simulated. WhatsApp was added later as an optional live demo (see below), through the
  `Outbound` / `Channel` seams and without changing the agent.
- Only the Reach phase, text only, a simulated clock (fixed on a Monday, the same in tests and demo),
  one clinic, an in-memory calendar and no time zones.

## How it is tested

| Layer | What it proves | Where |
|---|---|---|
| Unit | guardrail, "nearest valid time", calendar, validation of LLM output, rules | `tests/test_guardrails.py`, `test_calendar.py`, `test_extraction.py`, `test_llm.py`, `test_rules.py` |
| Scenarios | the agent's **decisions** in whole conversations, with a *scripted* extractor (each test states what each message means) | `tests/test_scenarios.py` |
| Invariants | rules that must hold in *any* conversation, checked automatically after every scenario: no contact outside hours, nothing after closing, counters within limits. A mutation test disables the guardrail and confirms the check fails | `tests/helpers.py::check_invariants`, `tests/test_invariants.py` |
| Eval | how well each extractor **reads** messages: 35 development + 21 held-out messages, labelled with the conversation state they arrive in | `evals/` |
| End-to-end | with `--llm`, the same scenarios run with the real model reading the messages (the last full run with DeepSeek, on 24 September, passed 149/149) | `pytest --llm deepseek` |
| WhatsApp adapters and launcher | Meta and Twilio signature checks, the launcher's pre-flight checks and webhook retries, Meta's URL verification, retried messages handled once, receipts skipped, the 24-hour window, routing each action to its channel, send failures. Offline, with locally signed requests, a fake sender and a fake Graph API | `tests/test_whatsapp.py`, `test_whatsapp_meta.py`, `test_live.py` |

The five required cases, in `tests/test_scenarios.py`:

| Case | Test |
|---|---|
| Clear request | `test_clear_request_is_booked_after_missed_call_and_callback` |
| Ambiguous preference | `test_ambiguous_preference_asks_for_clarification_then_continues` |
| Outside contact hours | `test_out_of_hours_preference_is_not_used_and_nearest_valid_time_is_proposed` |
| Human handoff | `test_clinical_question_hands_off_with_full_context` |
| No response | `test_no_response_follows_up_within_hours_then_stops_for_human_review` |

### Eval: rules vs LLM

The eval orders its metrics by what costs most to get wrong in this product:
**handoff recall** (a clinical question that never reaches a human is the worst possible error),
**invented times** (turning "mais logo", *later*, into a time means calling the patient at a time they
never gave), then accuracy and **unnecessary handoffs** (they cost staff time but put nobody at risk).
The rule-based (regex) extractor is the baseline: the LLM has to beat it by a margin that justifies
its cost and latency.

There are two sets. The **dev** set (35 messages) was used to tune the prompt and the rules. The
**held-out** set (21 new messages) was written and *committed before* any extractor was run on it
(commit `2fdec32`) and has never been used to tune anything. It is the honest estimate.

| | rules | `deepseek` | `deepseek-thinking` |
|---|---|---|---|
| **dev**: handoff recall | 100% | 100% | 100% |
| dev: invented times | 1/5 | 0/5 | 0/5 |
| dev: correct intent | 86% | 100% | 97% |
| **held-out**: handoff recall | **40%** | **100%** | 100% |
| held-out: invented times | 0/3 | 0/3 | 0/3 |
| held-out: correct intent | 52% | 95% | 100% |
| mean latency | 0 ms | ~0.9 s | ~1.4 s |

Model `deepseek-flash`, with reasoning off and on. There were 0 unnecessary handoffs in every case.

**Stability.** The default configuration (`deepseek`) then ran 5 times on each set:

| `deepseek`, 5 runs | dev | held-out |
|---|---|---|
| handoff recall | 100% in every run | 100% in every run |
| invented times | 0 in every run | 0 in every run |
| correct intent | 100% in every run | 95–100% |
| latency per message | p50 0.78 s, p95 1.02 s | p50 0.78 s, p95 1.02 s |

On dev every reading was identical across runs. On the held-out set only one message changed:
"Pode ser um dia destes" (*maybe some day*) was read as `unclear` in 3 of 5 runs instead of
`scheduling` with no time. Both lead to the same clarifying question.

What this taught me:

- **The regex looked safe and wasn't.** It had 100% handoff recall on the dev set it was written
  against, and 40% on the held-out set. It let through "parti um dente, está a doer imenso" (*I broke
  a tooth, it hurts a lot*: it knew "dor", *pain*, but not "doer", *to hurt*), a question about
  anaesthesia while breastfeeding, and a complaint, and it read "é a **segunda** vez" (*it's the second
  time*) as Monday (*segunda-feira*). Without the held-out set I would not have seen it.
- **The LLM's first run looked worse than the regex** (71% vs 80% exact extraction). But 7 of its 10
  failures were the eval penalising fields the agent never reads: the time of the chosen option,
  next to the correct option number. I fixed the metric to compare only what the agent uses for each
  intent, and re-scored the baseline under the same rule (`0e9ecab`).
- The 3 real failures had one cause: the model answered `accept` when nothing had been proposed. I
  fixed them with a general rule in the prompt, without copying the failing messages into it
  (`e33bea9`). Dev went from 91% to 100%, and the held-out set then scored 95%.
- **Reasoning doesn't pay off here.** It costs +60% latency with no improvement: each mode has one
  miss, on different sets, and both lead to the same clarifying question. In a voice agent, latency
  is patient experience, so reasoning is off by default. An early probe with a vague prompt suggested
  ~10 s per message; measured on the real prompt it is 1.4 s (`34c121e`).

## How to run

Requires Python 3.10 or later.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

pytest                            # everything offline, no API key
python -m reach_agent             # terminal demo (you play the patient)
python -m evals.run_eval          # baseline eval
```

In the demo: `/sem-resposta` (*no reply*) simulates the patient not answering, `/estado` (*state*)
shows the conversation memory, and `/trace` shows the instrumented events (each extraction with its
latency, guardrail decisions, etc.).

With a real LLM (costs credits). Any OpenAI-compatible API works. `reach_agent/llm.py` configures
`deepseek` (`deepseek-flash`, reasoning off), `deepseek-thinking` and `openai` (`gpt-4.1-mini`);
the model can be changed with `LLM_MODEL`.

```bash
$env:DEEPSEEK_API_KEY = "sk-..."  # PowerShell  (bash: export DEEPSEEK_API_KEY=sk-...)
python -m reach_agent --llm deepseek
python -m evals.run_eval rules deepseek                    # dev set
python -m evals.run_eval rules deepseek --dataset holdout  # held-out set
pytest --llm deepseek             # smoke test + eval thresholds + every scenario with the real model
```

The `openai` provider (with `OPENAI_API_KEY` and `--llm openai`) is implemented and tested against a
fake client, but I have not run it against the real API.

## Live on WhatsApp (optional)

The same agent can talk to a real phone over WhatsApp. Each channel has its own transport:
WhatsApp messages go through a provider to the phone, while the voice call stays simulated in the
terminal, where you pick up and type what the patient says. `agent.py` did not change for this; the
adapters only use the `Outbound` / `Channel` seams that were already there.

Tested live on 24 September 2026, from a real phone, through Meta's WhatsApp Cloud API:

```
[seg 21/09 14:14] WhatsApp <- 3519…: Olá, queria marcar uma consulta
[seg 21/09 14:14] O agente liga ao paciente. Atender? (s/n)          <- "n" typed in the terminal
[seg 21/09 14:14] WhatsApp -> 3519…: Olá tiago, daqui fala a assistente da Clínica Exemplo. Tentámos ligar-lhe [...]
[seg 21/09 14:14] WhatsApp <- 3519…: Estou a trabalhar, podem ligar depois das 18h
[seg 21/09 14:19] WhatsApp -> 3519…: Combinado! Ligamos-lhe hoje às 18:00.
[seg 21/09 18:00] Voz | Agente: [...] Tenho estas vagas para a sua consulta: 1) amanhã às 18:30 [...]
[seg 21/09 18:05] Voz | Agente: Ficou marcada a sua consulta para amanhã às 18:30. Até lá!
```

There are two adapters with the same shape: `whatsapp_meta.py` (Meta's Cloud API, the default) and
`whatsapp.py` (Twilio). What they take care of:

- **Authenticity:** every webhook request must be signed by the provider. Meta signs the raw body
  with HMAC-SHA256 and the App Secret; Twilio signs the URL and parameters with the auth token.
  Unsigned or forged → 403. Meta also checks the URL once, with a verify token, before using it.
- **Retries:** providers resend a message if they get no answer; each message id is acted on once.
- **Latency:** the webhook answers immediately; the agent and its LLM call run outside the request,
  so a slow model never causes a timeout and a duplicate delivery.
- **Noise:** delivery and read receipts arrive on the same webhook and are skipped.
- **WhatsApp's 24-hour rule:** free-form messages are only allowed within 24 hours of the patient's
  last WhatsApp message. Outside that window the adapter refuses to send and says a pre-approved
  template would be needed.

**Why Meta and not Twilio by default.** I first tested with Twilio. Messages *from* the phone reached
the agent, but every reply was refused: Twilio trial accounts may only send Twilio's own
pre-approved templates, never free text (error 21654, "ContentSid Required"). The adapter logged the
failure and the conversation carried on. Meta's test number, on a free developer account, can reply
with free text inside the 24-hour window, which is all this demo needs. The Twilio adapter still
works with an upgraded account (`--via twilio`).

Setup with Meta, once (about 30 minutes):

1. At [developers.facebook.com](https://developers.facebook.com/apps), create an app with the use
   case *Connect with customers through WhatsApp*. Under *Use cases → Customize → Step 1. Try it
   out*, note the *Phone Number ID* and the *WhatsApp Business account ID*, add your phone as a
   recipient (Meta sends it a code) and send the sample message to check that it arrives.
2. Get an access token. The one on that page lasts about 24 hours; for a demo you can start any
   day, create a system user token instead (Business settings → *System users* → add one, give it
   the app and the WhatsApp account, generate a token with `whatsapp_business_messaging` and
   `whatsapp_business_management`).
3. Copy `live.env.example` to `live.env` (ignored by Git) and fill it in, with the *App ID* and
   *App secret* from *App settings → Basic*.
4. Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
   (`winget install Cloudflare.cloudflared`). No account is needed.

Then, every time, one command:

```powershell
.\demo.ps1                 # Windows; elsewhere: python -m reach_agent.live --llm deepseek
```

It checks the token (and how long it has left), the App secret, the phone number, the port and the
LLM key, and stops with one clear line if something is wrong. Then it opens a cloudflared quick
tunnel, points the app's webhook at the tunnel's new address, links the test WhatsApp account to
the app if needed (easy to miss: without it the webhook is never called), and prints the number to
message. Conversations then run back to back; `/sair` or Ctrl+C closes everything, tunnel included.
From your phone, send "Olá, queria marcar uma consulta" (*Hi, I'd like to book an appointment*) and
answer the simulated call in the terminal.

With Twilio instead (needs an upgraded account to send replies): set `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` (the sandbox number) and `WHATSAPP_WEBHOOK_URL` (the
public `https://…/whatsapp` address, which Twilio signs), point the sandbox's *When a message comes
in* at it, and run `python -m reach_agent.whatsapp_demo --via twilio`.

Limits of the live demo: one patient at a time, state in memory, and the clock is still the
simulated Monday (so "hoje às 18:00" is simulated time and scheduled messages go out immediately).
A request with a bad signature gets a 403 but prints nothing in the terminal (the launcher's
checks catch a wrong App secret before that can happen).

## Limitations and next steps

- **The eval is small (56 messages) and I wrote all of it, held-out set included.** I wrote the
  held-out set after tuning the prompt, but the author is the same person. The next step would be
  real anonymised messages, or messages written by someone else.
- **Variance was measured for the default configuration only** (5 runs per set); `deepseek-thinking`
  ran once per set.
- The p95 latency (1.02 s) covers the extraction alone. A voice turn would add speech-to-text and
  text-to-speech on top.
- The eval is per message; conversation-level metrics (booking rate, number of turns) are missing.
- Time zones, public holidays and per-country contact rules (Wilco's site mentions *local rules* and
  the *patient's timezone*).
- Rigid templates: generating the text with the LLM would make messages more natural, but would need
  its own evaluation (tone, no promise the code did not make).
- State in memory and simulated timers; in production these would be a database and a scheduler.
- **WhatsApp's 24-hour rule is only enforced in the live adapter.** In the terminal simulation the agent
  sends a free-form WhatsApp message after a missed call even if the enquiry came from elsewhere
  (e.g. a web form). Real WhatsApp would refuse that; the first message would have to be a
  pre-approved template.
- **A deferred reminder is not cancelled.** If the reply window expires at 23:30, the reminder is held
  until 09:00 (guardrail), but if the patient replies in the meantime (say at 07:30), the simulation
  still sends it. In production the scheduler would cancel the pending send when a reply arrives.

## Structure

```
reach_agent/
  agent.py            state machine: every decision
  guardrails.py       contact window + nearest valid time
  models.py           Conversation (state/memory), Extraction, Outbound, Handoff
  extraction.py       Extractor interface + validation + scripted extractor for tests
  llm.py              LLMExtractor: DeepSeek or OpenAI (any compatible API)
  rules.py            rule-based extractor (offline baseline)
  clinic_calendar.py  fake calendar
  messages.py         everything the agent says to the patient
  simulation.py       simulated clock, shared by the demo and the tests
  cli.py              terminal demo
  whatsapp.py         WhatsApp transport through Twilio (signature, retries), sender, 24 h window
  whatsapp_meta.py    WhatsApp transport through Meta's Cloud API (URL check, signature, retries), sender
  whatsapp_demo.py    live demo: patient on real WhatsApp, calls simulated in the terminal
  live.py             the live demo in one command: checks, tunnel, webhook (demo.ps1 on Windows)
data/calendar.json    the week's slots
evals/                dev and held-out sets + comparison script
tests/                pytest
```

The commit history (`git log --oneline`) shows how it was built, step by step.
