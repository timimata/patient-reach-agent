# patient-reach-agent

[![tests](https://github.com/timimata/patient-reach-agent/actions/workflows/tests.yml/badge.svg)](https://github.com/timimata/patient-reach-agent/actions/workflows/tests.yml)

I built this to prepare for my interview at Wilco. It is a small version of one part of what Wilco
does: **Reach**, turning a patient's enquiry into a booked appointment.

It is not a copy of the product. There is no real telephony, only the decisions, and most of my time
went into testing them properly.

## What it does

A patient asks for an appointment. The agent calls and nobody answers, so it sends a WhatsApp message
asking when to call back. The patient says they're at work and asks for a call after six. The agent
calls back at 18:00, offers three slots and books the one the patient picks.

```
[seg 21/09 14:14] O agente liga ao paciente. Atender? (s/n)> n
[seg 21/09 14:14] WhatsApp | Agente: Olá Ana, daqui fala a assistente da Clínica Exemplo. Tentámos ligar-lhe [...]
Paciente> Estou a trabalhar, podem ligar depois das 18h?
[seg 21/09 14:19] WhatsApp | Agente: Combinado! Ligamos-lhe hoje às 18:00.
[seg 21/09 18:00] O agente liga ao paciente. Atender? (s/n)> s
[seg 21/09 18:00] Voz | Agente: Olá Ana, [...] Tenho estas vagas para a sua consulta:
        1) amanhã às 18:30
        2) quarta, 23/09, às 19:00
        3) quinta, 24/09, às 18:00
Paciente> a primeira
[seg 21/09 18:05] Voz | Agente: Ficou marcada a sua consulta para amanhã às 18:30. Até lá!
```

The clinic is Portuguese, so the patient sees Portuguese. The flow is the example on
[getwilco.ai](https://getwilco.ai), and so are the two rules the agent follows:

- **It only contacts patients between 09:00 and 20:00.** If someone asks for a call at 21:00, the
  agent doesn't do it. It explains why, proposes the nearest time that works (tomorrow at 09:00) and
  waits for a yes.
- **It knows when to step aside.** A clinical question, a complaint, three contacts with no reply, a
  message it still can't understand after asking twice, or an LLM error: in all of these, it stops
  and hands the conversation to a person, with the full transcript and the reason.

## The main idea: the LLM reads, the code decides

The LLM does one job. It reads the patient's message and turns it into a small piece of JSON: what
they want, which day, which times, which option. The code checks that JSON and makes every decision:
when to call, what to offer, when to stop.

I chose this split because:

- **Some rules have to hold every time, not almost every time.** Code can guarantee that, and tests
  can prove it.
- **No message can talk the agent into anything.** The model can't send, book or schedule. At worst
  it misreads a message, and the rules still apply.
- **The logic can be tested without an LLM.** 140 tests run offline in under a second.
- **Everything the agent says is a fixed template**, so a clinic could review every sentence. The
  price is that it sounds a bit rigid.

## Is the LLM worth it?

I compared it with a simple regex baseline, on patient messages I wrote and labelled by hand. The
number I care about most is **handoff recall**: a clinical question that never reaches a person is
the worst mistake this system can make.

I kept 21 of those messages aside and committed them (`2fdec32`) before running anything on them, so
I couldn't tune anything to fit them:

| On the 21 held-out messages | regex | LLM (DeepSeek) |
|---|---|---|
| sent to a person when they needed one | **40%** | **100%**, in each of 5 runs |
| understood correctly | 52% | 95–100% |
| time per message | instant | ~1 s (p95 1.02 s) |

On the 35 messages I wrote it against, the regex looked perfect: 100% handoff recall. On new messages
it let through *"parti um dente, está a doer imenso"* (*I broke a tooth, it hurts a lot*). It knew
"dor" (*pain*) but not "doer" (*to hurt*). Without the held-out set I would never have seen that.

Two other things I learned:

- The LLM's first score was *worse* than the regex's. Most of its misses were on fields the agent
  never reads, so I fixed the metric and re-scored both sides under the same rule (`0e9ecab`).
- Turning on the model's reasoning made it 60% slower and no more accurate, so it stays off.

## How it's tested

- **Whole conversations.** Each scenario test plays a full conversation and checks what the agent
  decided. The five required cases are in `tests/test_scenarios.py`: a clear request, an ambiguous
  preference, a request outside contact hours, a human handoff and a patient who never replies.
- **Rules that must always hold.** After every scenario, a check confirms that nothing was sent
  outside contact hours or after the conversation closed. A mutation test switches off the contact-
  hours guardrail to prove that check really catches it.
- **The eval** above, in `evals/`.
- **With the real model.** `pytest --llm deepseek` runs the same scenarios with DeepSeek reading the
  messages. The last full run, on 24 September, passed 149 of 149.

## Try it

Requires Python 3.10 or later.

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

pytest                            # everything offline, no API key needed
python -m reach_agent             # you play the patient
```

In the demo, `/sem-resposta` means the patient doesn't reply, `/estado` shows what the agent
remembers, and `/trace` shows what the LLM read.

With a real LLM (uses API credits):

```bash
$env:DEEPSEEK_API_KEY = "sk-..."  # PowerShell  (bash: export DEEPSEEK_API_KEY=sk-...)
python -m reach_agent --llm deepseek
python -m evals.run_eval rules deepseek --dataset holdout
pytest --llm deepseek
```

Any OpenAI-compatible API works (see `reach_agent/llm.py`). The `openai` provider is implemented and
tested against a fake client, but I haven't run it against the real API.

## Live on WhatsApp

The same agent can talk to a real phone. On 24 September I went from "Olá" to a booked appointment on
my own phone, through Meta's WhatsApp Cloud API. The agent's code didn't change for this: an adapter
plugs into it, and the calls stay simulated in the terminal.

The adapter checks that every webhook request is really from Meta (forged ones get a 403), handles a
message only once even if it arrives twice, answers straight away so a slow model never causes a
retry, and respects WhatsApp's rule that free-form messages are only allowed within 24 hours of the
patient's last message.

I started with Twilio, but trial accounts can't send free text (error 21654), so every reply was
refused. The system failed safely, and I wrote a Meta adapter instead. The Twilio one still works on
a paid account.

**Setup, once (about 30 minutes):**

1. At [developers.facebook.com](https://developers.facebook.com/apps), create an app with the use
   case *Connect with customers through WhatsApp*. Note the *Phone Number ID* and *WhatsApp Business
   account ID*, and add your phone as a recipient.
2. Create a long-lived token: Business settings → *System users*, with `whatsapp_business_messaging`
   and `whatsapp_business_management`.
3. Copy `live.env.example` to `live.env` and fill it in (it is ignored by Git).
4. Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
   (`winget install Cloudflare.cloudflared`). No account needed.

**Then, every time:**

```powershell
.\demo.ps1                 # elsewhere: python -m reach_agent.live --llm deepseek
```

It checks the setup, opens a tunnel, points Meta's webhook at it and prints the number to message.
Answer the simulated calls in the terminal; `/sair` or Ctrl+C closes everything.

With Twilio instead: set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` and
`WHATSAPP_WEBHOOK_URL` (the public `https://…/whatsapp` address), point the sandbox at it and run
`python -m reach_agent.whatsapp_demo --via twilio`.

## What's missing

- **The eval is small, and I wrote all of it.** That's 56 messages, held-out set included. The next
  step would be real anonymised messages, or ones written by someone else.
- **No real voice.** The ~1 s latency covers reading the message only; speech-to-text and
  text-to-speech would come on top.
- **One clinic, one simulated week.** The state lives in memory and there's a fake clock. There are
  no time zones, holidays or country-specific contact rules.
- **Two known gaps.** WhatsApp's 24-hour rule is only enforced in the live adapter, not in the
  terminal simulation. A reminder pushed to 09:00 isn't cancelled if the patient replies before then.

## Where things are

```
reach_agent/
  agent.py            every decision the agent makes
  guardrails.py       contact hours and the nearest valid time
  llm.py / rules.py   the two ways of reading a message: LLM or regex
  messages.py         everything the agent says
  cli.py              terminal demo
  whatsapp_meta.py    WhatsApp through Meta (whatsapp.py: through Twilio)
  live.py             the one-command live demo
data/calendar.json    the week's free slots
evals/                the labelled messages and the comparison script
tests/                pytest
```

The commit history (`git log --oneline`) shows how it was built, step by step.
