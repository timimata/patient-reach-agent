# patient-reach-agent

Para me preparar para a entrevista na Wilco, construí uma versão simplificada e testada do
tipo de problema que a Wilco resolve: a fase **Reach**, transformar o pedido (enquiry) de um paciente numa
consulta marcada. O objetivo é mostrar como penso sobre isto. Não é uma réplica do produto: é só a
lógica de decisão, em texto e sem telefonia real, com o esforço concentrado em testá-la a sério.

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

## Como isto mapeia para o fluxo Reach

O fluxo segue o exemplo que a Wilco mostra em [getwilco.ai](https://getwilco.ai):

| No site da Wilco | Neste projeto |
|---|---|
| *Call 09:15: no answer. The enquiry stays open.* | `ReachAgent.start()` agenda a chamada; `on_call_result(answered=False)` |
| *WhatsApp 09:17: sent a message to find a better time* | `_no_answer()` envia WhatsApp |
| *"I'm at work. Could you call after six?"* | o extractor (LLM) lê a mensagem e devolve `scheduling, earliest=18:00` |
| *Flow updated: call back at 18:30* | `plan_contact()` cruza a preferência com a janela 09:00–20:00: callback às 18:00 |
| *Callback: spoke with the patient and booked the visit* | `_offer_slots()` (vagas de `data/calendar.json`, filtradas pela preferência lembrada) e depois `_book()` |
| *Strict calling-hour limits* | `ContactWindow` + `_within_contact_hours()`, o único ponto por onde passa contacto iniciado pelo agente |
| *Bring in your team at contact limits or clinical questions* | `_hand_off()`: pergunta clínica, reclamação, 3 tentativas sem resposta, mensagem não percebida, falha do LLM |

```
 enquiry ─► CALLING ──atende──► OFFERING_SLOTS ──escolhe──► BOOKED
             │   ▲                  └─ "tem na sexta?" ─► volta a oferecer
    não atende   │ hora acordada
             ▼   │
        AWAITING_REPLY ──3 contactos seguidos sem resposta──► HANDED_OFF
 (em qualquer fase: clínico / reclamação / não percebido 3x / erro do LLM ─► HANDED_OFF)
```

## Decisões de desenho

1. **O LLM só lê; o código decide.** O LLM converte texto livre numa `Extraction` (intenção, data,
   horas, opção escolhida) em JSON, e esse JSON é sempre validado em código antes de ser usado.
   *Quando* ligar, o que oferecer e quando parar é código determinístico em `agent.py`. Assim a lógica
   testa-se sem LLM, e uma mensagem bem escrita não consegue convencer o agente a violar uma regra.
   Como a validação vive no código, trocar de fornecedor é só configuração: a OpenAI garante o
   schema no servidor, a DeepSeek só garante JSON válido, e o resto do sistema não muda.
2. **O guardrail é código, num único ponto.** Todo o contacto iniciado pelo agente (chamadas,
   follow-ups, lembretes) passa por `_within_contact_hours()`. Uma preferência fora da janela
   ("só depois das 21h") nunca é usada: o agente explica e *propõe* a hora válida mais próxima que não
   seja mais cedo do que o pedido, e só agenda depois de o paciente aceitar. Respostas imediatas a uma
   mensagem do paciente não são contacto iniciado pelo agente, por isso não ficam sujeitas à janela.
3. **Na dúvida, um humano.** Se o LLM falha (rede, JSON inválido), a mensagem vai para um humano;
   não se adivinha. Ao fazer handoff, o agente regista o motivo, a mensagem que o causou, a fase, a
   preferência e a transcrição completa, cancela qualquer callback pendente e deixa de responder.
4. **Memória explícita.** `Conversation` guarda a preferência dita, a proposta pendente, as vagas
   oferecidas e os contadores. É isso que permite que um "sim" signifique "sim à proposta das 09:00"
   e que "a de quarta" aponte para a vaga certa. Essa memória vai como contexto para o extractor.
5. **Respostas por template** (`messages.py`), não geradas: a clínica pode rever cada frase e os
   testes podem verificá-las. O preço é soarem rígidas (ver limitações).

## Âmbito: o que ficou de fora e porquê

- **Sem telefonia nem WhatsApp reais.** O que quis mostrar é a lógica de decisão e como a testar.
  Integrar Twilio/WhatsApp Business gastaria o tempo disponível em ligações a APIs e não em raciocínio.
  `Outbound` e `Channel` marcam onde essa integração entraria.
- Só a fase Reach, só texto, um relógio simulado (fixo numa segunda-feira, igual nos testes e na
  demo), uma clínica, calendário em memória e sem fusos horários.

## Como está testado

| Camada | O que prova | Onde |
|---|---|---|
| Unitários | guardrail, "hora válida mais próxima", calendário, validação do output do LLM, regras | `tests/test_guardrails.py`, `test_calendar.py`, `test_extraction.py`, `test_llm.py`, `test_rules.py` |
| Cenários | as **decisões** do agente em conversas completas, com um extractor *scripted* (cada teste diz o que a mensagem significa) | `tests/test_scenarios.py` |
| Invariantes | regras que têm de valer em *qualquer* conversa, verificadas automaticamente no fim de cada cenário: nenhum contacto fora de horas, nada depois de fechar, contadores dentro dos limites. Um teste de mutação desliga o guardrail e confirma que a verificação falha | `tests/helpers.py::check_invariants`, `tests/test_invariants.py` |
| Eval | quão bem cada extractor **lê** mensagens: 35 mensagens de desenvolvimento + 21 *held-out*, rotuladas com o estado da conversa em que chegam | `evals/` |
| End-to-end | com `--llm`, os mesmos cenários correm com o modelo real a ler as mensagens (com a DeepSeek passam os 112 testes) | `pytest --llm deepseek` |

Os cinco casos obrigatórios, em `tests/test_scenarios.py`:

| Caso | Teste |
|---|---|
| Pedido claro | `test_clear_request_is_booked_after_missed_call_and_callback` |
| Preferência ambígua | `test_ambiguous_preference_asks_for_clarification_then_continues` |
| Fora do horário | `test_out_of_hours_preference_is_not_used_and_nearest_valid_time_is_proposed` |
| Handoff para humano | `test_clinical_question_hands_off_with_full_context` |
| Sem resposta | `test_no_response_follows_up_within_hours_then_stops_for_human_review` |

### Eval: regras vs LLM

O eval ordena as métricas pelo que custa mais errar neste produto:
**handoff recall** (uma pergunta clínica que não chega a um humano é o pior erro possível),
**horas inventadas** (transformar "mais logo" numa hora é ligar ao paciente numa hora que ele não
deu), depois exatidão e **handoffs desnecessários** (custam tempo à equipa, mas não põem ninguém em risco).
O extractor de regras (regex) serve de baseline: o LLM tem de mostrar que é melhor por uma margem que
justifique o custo e a latência.

Há dois conjuntos. O **dev** (35 mensagens) foi usado para afinar o prompt e as regras. O
**held-out** (21 mensagens novas) foi escrito e *commitado antes* de correr qualquer extractor nele
(commit `004c092`) e nunca serviu para afinar nada. É a estimativa honesta.

| | regras | `deepseek` | `deepseek-thinking` |
|---|---|---|---|
| **dev**: handoff recall | 100% | 100% | 100% |
| dev: horas inventadas | 1/5 | 0/5 | 0/5 |
| dev: intenção correta | 86% | 100% | 97% |
| **held-out**: handoff recall | **40%** | **100%** | 100% |
| held-out: horas inventadas | 0/3 | 0/3 | 0/3 |
| held-out: intenção correta | 52% | 95% | 100% |
| latência média | 0 ms | ~0,9 s | ~1,4 s |

Modelo `deepseek-flash`, com o raciocínio desligado e ligado. Cada configuração correu uma vez em
cada conjunto. Houve 0 handoffs desnecessários em todos os casos.

O que aprendi com isto:

- **A regex parecia segura e não era.** Teve 100% de handoff recall no dev, onde foi escrita, e 40%
  no held-out. Deixou passar "parti um dente, está a doer imenso" (conhecia "dor", mas não "doer"),
  uma pergunta sobre anestesia durante a amamentação e uma reclamação, e leu "é a **segunda** vez"
  como segunda-feira. Sem o held-out não o teria visto.
- **A primeira corrida do LLM pareceu pior do que a regex** (71% contra 80% de extração exata). Mas 7
  das 10 falhas eram o eval a penalizar campos que o agente nem lê: a hora da opção escolhida, ao lado
  do número certo. Corrigi a métrica para comparar só o que o agente usa em cada intenção e voltei a
  avaliar a baseline com a mesma regra (`9012ba8`).
- As 3 falhas reais tinham uma causa comum: o modelo respondia `accept` quando não havia nada
  proposto. Corrigi-as com uma regra geral no prompt, sem copiar as mensagens que falhavam
  (`d25cd9c`). O dev passou de 91% para 100%, e depois o held-out deu 95%.
- **O raciocínio não compensa aqui.** Custa +60% de latência sem melhorar nada: cada modo tem uma
  falha, em conjuntos diferentes, e as duas levam à mesma pergunta de clarificação. Num agente de
  voz, a latência é experiência do paciente, por isso fica desligado por defeito. Uma primeira sonda,
  com um prompt vago, sugeria ~10 s por mensagem; medido no prompt real, são 1,4 s (`da5de63`).

## Como correr

Requer Python 3.10 ou superior.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

pytest                            # tudo offline, sem API key
python -m reach_agent             # demo no terminal (tu és o paciente)
python -m evals.run_eval          # eval da baseline
```

Na demo: `/sem-resposta` simula o paciente não responder, `/estado` mostra a memória da conversa,
`/trace` mostra os eventos instrumentados (cada extração com latência, decisões do guardrail, etc.).

Com um LLM real (gasta créditos). Funciona qualquer API compatível com a da OpenAI. Em
`reach_agent/llm.py` estão configurados `deepseek` (`deepseek-flash`, sem raciocínio),
`deepseek-thinking` e `openai` (`gpt-4.1-mini`); o modelo muda-se com `LLM_MODEL`.

```bash
$env:DEEPSEEK_API_KEY = "sk-..."  # PowerShell  (bash: export DEEPSEEK_API_KEY=sk-...)
python -m reach_agent --llm deepseek
python -m evals.run_eval rules deepseek                    # conjunto dev
python -m evals.run_eval rules deepseek --dataset holdout  # held-out
pytest --llm deepseek             # smoke test + limiares do eval + todos os cenários com o modelo real
```

O fornecedor `openai` (com `OPENAI_API_KEY` e `--llm openai`) está implementado e testado com um
cliente falso, mas não o corri contra a API real.

## Limitações e próximos passos

- **O eval é pequeno (56 mensagens) e fui eu que escrevi tudo, held-out incluído.** Escrevi o
  held-out depois de afinar o prompt, mas quem o escreveu é a mesma pessoa. O passo seguinte seriam
  mensagens reais anonimizadas ou escritas por outra pessoa.
- **Variância do LLM:** cada configuração correu uma vez (a exceção foi o dev com `deepseek`, que correu
  duas vezes antes da mudança de prompt e deu o mesmo resultado). Correria N vezes e reportaria a variação.
- Reporto a latência média; para voz importa mais a cauda (p95).
- O eval é por mensagem; faltam métricas ao nível da conversa (taxa de marcação, nº de turnos).
- Fusos horários, feriados e regras de contacto por país (o site da Wilco fala em *local rules* e
  *patient's timezone*).
- Templates rígidos: gerar o texto com o LLM tornaria as mensagens mais naturais, mas precisaria de
  avaliação própria (tom, nenhuma promessa que o código não fez).
- Estado em memória e timers simulados; em produção seriam uma base de dados e um scheduler.

## Estrutura

```
reach_agent/
  agent.py            máquina de estados: todas as decisões
  guardrails.py       janela de contacto + hora válida mais próxima
  models.py           Conversation (estado/memória), Extraction, Outbound, Handoff
  extraction.py       interface Extractor + validação + extractor scripted para testes
  llm.py              LLMExtractor: DeepSeek ou OpenAI (qualquer API compatível)
  rules.py            extractor de regras (baseline offline)
  clinic_calendar.py  calendário falso
  messages.py         tudo o que o agente diz ao paciente
  simulation.py       relógio simulado, partilhado pela demo e pelos testes
  cli.py              demo no terminal
data/calendar.json    vagas da semana
evals/                conjuntos dev e held-out + script de comparação
tests/                pytest
```

O histórico de commits (`git log --oneline`) mostra a construção passo a passo.
