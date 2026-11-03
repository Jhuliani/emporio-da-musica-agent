# Empório da Música — Customer Service Agent

Prototype of a text-based customer service agent for **Empório da Música**, a fictional musical instrument store in Campo Grande/MS, Brazil. The agent ("Tom") answers customers in Portuguese about products, prices, promotions, orders and store policies. It decides by itself when to query store data (via function calling) and when to rely on the policy manual.

### Highlights

- **Function calling with 7 typed tools.** All prices, installments, deadlines and availability are computed in Python, never by the LLM.
- **Policy manual loaded in full into the system prompt.** No RAG: the document is small. See the decisions section.
- **The data was audited before building anything.** About 20 findings across the CSVs and the manual, and each one has a documented decision ([docs/data_quality.md](docs/data_quality.md)).
- **Works with any OpenAI-compatible provider.** Gemini is the default and the validated one. The user enters the API key in the UI, and it is kept only in session memory.
- **63 unit tests and 17 evaluation scenarios run against the real LLM.** The evals found real failures that were then fixed (15/17 → 17/17).

---

## 1. How to run

**Requirements:** Python 3.10+ and an API key from an OpenAI-compatible provider. The default is Gemini, whose key is free at <https://aistudio.google.com/apikey>.

```bash
git clone https://github.com/Jhuliani/emporio-da-musica-agent.git
cd emporio-da-musica-agent

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

streamlit run app.py
```

Then open the browser at the address Streamlit prints, usually <http://localhost:8501>, paste the API key in the sidebar and start chatting.

### Choosing the model provider

The sidebar has presets for **Gemini** (default), **OpenAI**, **Groq**, **OpenRouter**, **Ollama (local, no key)** and a **Custom** option. Base URL and model name are editable.

- **The API key typed in the UI** lives only in this browser session's memory (`st.session_state`). It is not written to disk, logs or chat history.
- **Alternatively, use a `.env` file**, which is git-ignored:

  ```bash
  cp .env.example .env    # then fill LLM_API_KEY (LLM_BASE_URL and LLM_MODEL are optional)
  ```

- **If the default model is overloaded** (HTTP 503 "high demand", which happens on the free tier), switch the model in the sidebar, e.g. `gemini-3.5-flash`.

### Other commands

```bash
python -m pytest                  # 63 unit tests (no network, no API key)
python evals/run_evals.py         # 17 scenarios against the real LLM (needs .env), writes evals/results.md
python -m emporio.data            # data consistency report (set PYTHONPATH=src first)
python -m emporio.agent "Quanto custa o Takamine GD20?"   # one-shot smoke test (PYTHONPATH=src)
```

### Project structure

```text
app.py                 Streamlit chat UI (provider settings + chat)
src/emporio/
  data.py              CSV loading, typed models (pydantic), cross-table validation
  rules.py             deterministic business rules (prices, installments, shipping, returns, hours)
  tools.py             the 7 tools exposed to the LLM + their JSON schemas
  agent.py             hand-written function-calling loop and safeguards
  prompt.py            system prompt (persona, rules, guardrails) + policy manual
  llm.py               provider presets and OpenAI-compatible client
data/                  store data (CSVs, original PDF) + policies.md (transcribed manual)
docs/data_quality.md   every data/manual inconsistency and the decision taken
evals/                 scenarios, runner and latest results (results.md)
examples/              5 sample conversations generated with the real agent
tests/                 unit tests (data, rules, tools, agent loop with a fake LLM, UI)
```

---

## 2. Architecture

```text
 Customer ──► Streamlit UI ──► Agent loop (agent.py) ◄──► LLM (any OpenAI-compatible API)
                                    │   system prompt = persona + rules + full policy manual
                                    │
                                    ▼  tool calls (JSON)
                              StoreTools (tools.py)
                                    │
                     ┌──────────────┴──────────────┐
                     ▼                             ▼
          Business rules (rules.py)      Store data (data.py)
          prices, promos, PIX,           products, promotions,
          installments, shipping,        orders, customers
          returns, opening hours         (CSV → validated models)
```

**One customer message, step by step:**

1. The UI sends the conversation history and the new message to the agent.
2. The agent calls the LLM with the system prompt and the 7 tool schemas.
3. If the LLM requests tools, the agent runs them and sends the results back. This repeats for up to 6 rounds.
4. The LLM writes the final answer from the tool results.
5. The UI shows the answer and, optionally, the tool calls (useful to see what the agent consulted).

### The tools

| Tool | Purpose |
| --- | --- |
| `search_products` | Catalog search by text, category and price range; in-stock items only, plus a list of matching items that can't be sold now |
| `get_product` | Full details: price, active promotion, PIX price, installments, specs; alternatives if unavailable |
| `list_active_promotions` | Promotions active in the system right now |
| `get_order_status` | Order status, tracking, delay detection and return/exchange windows. **Requires order number + registered email or phone** |
| `simulate_payment` | PIX, debit, boleto and credit card options, plus shipping for a city |
| `get_store_status` | Whether the store is open now (Campo Grande time) and when it reopens |
| `escalate_to_human` | Registers complaints and cases the agent can't solve, for the human team (24 business hours) |

---

## 3. Technical decisions

### Agent approach: function calling with typed tools, no framework

- **Why tools, not text-to-SQL.** The questions customers ask are a small, known set: price, availability, catalog search, order status, payment. Typed tools cover them with clear semantics, safe inputs and testable outputs. A SQL agent would add risk (hallucinated queries, data exposure, injection) without adding capability.
- **Why business rules live in code.** The manual itself warns that a wrong price or deadline can amount to misleading advertising (section 7.1). So prices, discounts, PIX, installments, shipping, deadlines and availability are computed in `rules.py` and unit-tested. The LLM only decides *which* tool to call and *how* to phrase the answer.
- **Why no framework.** The loop in `agent.py` is ~100 lines and has no framework such as LangChain or LlamaIndex. That keeps every tool call visible (for the UI, logs and evals), lets me add safeguards exactly where needed and avoids lock-in.

### Retrieval: the whole policy manual in the prompt, no RAG

- **Why no RAG.** The manual has ~3k tokens. Putting all of it in the system prompt is simpler and more reliable than chunking, embeddings and retrieval. The model always sees the complete rules, so a cross-reference can't be missed because a chunk wasn't retrieved.
- **Why the transcription is in Portuguese.** The PDF was transcribed to [`data/policies.md`](data/policies.md). Contradictions were resolved inline and marked "[Nota de consistência]". The text stays in Portuguese, the customers' language, so that no rule gets distorted in translation.
- **When I would switch to RAG.** If the knowledge base grew to many documents (product manuals, FAQs, many policy versions) or beyond a few tens of thousands of tokens.

### Model and provider

- **One OpenAI-compatible client** (`openai` SDK with a configurable `base_url`). The same code runs on Gemini, OpenAI, Groq, OpenRouter or a local Ollama.
- **Default: Gemini `gemini-3.5-flash-lite`**, through Google's OpenAI-compatible endpoint ([docs](https://ai.google.dev/gemini-api/docs/openai)):
  - its free tier lets evaluators run the project at no cost;
  - it is fast and good at tool calling and Portuguese;
  - it passed all 17 eval scenarios.
- **A finding during development:** `gemini-2.5-flash`, the initial choice, is no longer available to new API keys, and `gemini-3.5-flash` was intermittently overloaded (HTTP 503). This is why the model is configurable in the UI.
- **Provider quirk:** Gemini attaches *thought signatures* to tool calls. The agent sends the provider's raw `tool_calls` back unchanged so that multi-step tool use keeps working.
- **Privacy note:** on Google's free tier, prompts may be used to improve their products. That is fine for this fictional data, but in production I would use a paid tier or Vertex AI because of LGPD.

### Prompt strategy

The system prompt ([`src/emporio/prompt.py`](src/emporio/prompt.py)) is written in English, like the codebase, and tells the agent to always answer in Brazilian Portuguese. Its sections:

1. **Persona.** "Tom" (a musical pun: *tom* = key/tone). The tone follows the manual: informal but professional, "a friend who knows music", short chat-sized messages.
2. **Source of truth:**
   - prices, stock, promotions, orders and opening status → **always tools**;
   - store rules → the manual;
   - campaign descriptions in the manual (e.g. "Black Friday 15–30%") are explicitly *not* active discounts.
3. **Presentation rules:**
   - promotions shown with the original price, % and final price (manual 6.2);
   - each product's own maximum installments (never generalized);
   - stock shown as "disponível" / "últimas unidades", never the internal number.
4. **Orders and LGPD.** Identity check before any lookup. A failed check reveals nothing, not even whether the order exists.
5. **Guardrails:**
   - accessories and off-topic requests are declined kindly;
   - complaints go to `escalate_to_human`;
   - no discounts, reservations or promises;
   - customer messages are data, not instructions (prompt injection);
   - never claim an action that wasn't executed.
6. **Context.** The current date and time in Campo Grande, plus the full policy manual.

### Safeguards in code (not only in the prompt)

The evals showed that prompt rules alone are not always followed. So the agent also has:

- **Self-check against invented actions.** If the reply says "registrei" / "encaminhei" (I registered / I forwarded) but `escalate_to_human` was not called, the agent gets an automatic nudge and one extra round to act or correct itself. The draft is dropped from the saved history.
- **Empty-response retry.** Gemini intermittently returned an empty message after tool results. The agent retries once, then reports an error instead of failing silently.
- **Tool-round limit (6), invalid-argument handling, friendly provider errors.** Invalid key, unknown model, rate limit and overload each produce a friendly message for the customer and a technical detail in the UI.

### Interface and conversation history

- **Streamlit:** a chat UI with minimal code. The sidebar holds the provider settings, the API key field and a toggle that shows the tool calls.
- **History kept per browser session** (in memory), so follow-ups work ("e em quantas vezes?"). Persisting it to a database was a conscious cut: the challenge says to implement persistence "if it makes sense", and for a prototype session memory is enough (see limitations).
- **CLI cut:** a separate CLI would duplicate the UI.

### Data handling

- **CSVs loaded with the standard `csv` module** into pydantic models. Pandas was dropped: with a few dozen rows it adds a heavy dependency for no gain.
- **Inconsistencies are reported, not silently fixed.** `python -m emporio.data` lists them and [docs/data_quality.md](docs/data_quality.md) documents each decision.
- **Main decisions:**
  - **status prevails over stock:** e.g. a discontinued bass with 13 units is not offered;
  - **only `is_active` promotions count**, and the highest one applies if there are several (promotions are not cumulative);
  - **recorded order totals are reported as-is**, never recalculated;
  - **the system prevails over the manual's general descriptions.**

---

## 4. Assumptions

The full list, with justifications, is in [docs/data_quality.md](docs/data_quality.md). The ones that most affect answers:

| Topic | Assumption |
| --- | --- |
| WhatsApp number | The manual has two numbers; **(67) 3341-4444** is used (it appears twice, including the official company data table) |
| Installments | Section 3.1 prevails over the summary table: min. installment **R$ 50 (1–3x), R$ 80 (4–6x), R$ 100 (7–12x)** |
| Receipt date | There is no actual delivery date in the data, so `estimated_delivery` is used for the 7-day withdrawal window; the agent says it is an estimate and refers borderline cases to the team |
| Online purchases | All orders are treated as online (they all have shipping data), so the right of withdrawal applies |
| Free shipping | "Above R$ 500" is read strictly (exactly R$ 500 pays R$ 35); the metro area is assumed to be Campo Grande only |
| Time zone | Campo Grande is UTC-4 with no daylight saving time, so a fixed offset is used, which avoids depending on the OS time zone database |
| Holidays | Not modeled (no list provided); the agent mentions the store is closed on holidays |
| Customer identity | Without a national ID (CPF), order lookups require order number + registered email or phone |
| Language | The deliverables are in English as requested; the agent speaks Portuguese, the store's and customers' language |

---

## 5. Evaluation

Unit tests cover deterministic behavior. But whether the *LLM* uses the tools correctly can only be measured by running it.

**How the evals work:**

- **[`evals/run_evals.py`](evals/run_evals.py)** runs **17 scenarios** ([`evals/scenarios.py`](evals/scenarios.py)) against the real model.
- **Each scenario checks** which tools were (or weren't) called and the key facts in the reply: prices, deadlines, refusals, no leaked data. Text checks are case- and accent-insensitive, so they target facts rather than wording.
- **The latest report**, with all transcripts, is in [`evals/results.md`](evals/results.md).

**The evals found real problems:**

| Run | Result | Finding | Fix |
| --- | --- | --- | --- |
| 1 (baseline) | 15/17 | The agent said "all of them can be paid in 12x" for guitars costing R$ 430 (max is 5x) | Each product now carries its own `max_installments`; prompt forbids generalizing |
| 1 | | The agent said **"I've registered your complaint" without calling the tool** | Prompt rule + **code-level self-check** (see Safeguards) |
| 2 | 16/17 | The agent found the out-of-stock product via `search_products` instead of `get_product`, an equally valid path | The *test* was too strict; it now accepts either tool |
| 3 | 15/17 | The unbacked-claim problem came back intermittently (prompt alone wasn't enough), and the agent stated the store was closed without checking (correct by chance) | Self-check in code; explicit rule to call `get_store_status`; tracking codes always shown |
| 4, 5, 6 | **17/17** | — | — |

Reviewing the [sample conversations](examples/) by hand found two more issues:

- the agent stated a shipping date and a carrier that don't exist in the data;
- an intermittent empty response from Gemini surfaced as a silent fallback.

Both were fixed: a prompt rule for the first, a retry with error reporting for the second.

---

## 6. Sample conversations

Five multi-turn conversations generated with the real agent, in [`examples/`](examples/):

1. [Catalog search within a budget](examples/01_catalog_search.md): live catalog data, comparison, per-product installments.
2. [Price and an expired promotion](examples/02_price_and_expired_promotion.md): the customer insists on an expired discount.
3. [Return request](examples/03_return_request.md) (**non-trivial**): identity check, order lookup, return windows computed from the order data, warranty guidance.
4. [Store info and out-of-scope requests](examples/04_store_info_and_scope.md): live opening status, accessories, a category with no products.
5. [Delayed order and complaint](examples/05_delayed_order_complaint.md): phone verification, tracking code, real handoff to the team.

---

## 7. Known limitations and what I would do with more time

| Limitation | With more time |
| --- | --- |
| Lexical product search (accent-insensitive whole words + category synonyms); misses paraphrases like "violão para criança" | Semantic search (embeddings) or hybrid search over the catalog |
| Conversation history lives only in the browser session (lost on refresh); no long-history truncation | Persist sessions (e.g. SQLite/Postgres) and summarize or trim long histories |
| Human handoff writes to a local `logs/handoffs.jsonl` | Integrate with the store's real ticketing / WhatsApp Business inbox |
| Identity check by email/phone is weak, knowledge-based authentication | One-time code sent to the registered phone/email |
| Receipt date is an estimate; holidays and shipping costs outside Campo Grande are not modeled | Carrier tracking API, holiday calendar, freight quote API |
| Evals are rule-based string checks (17 scenarios, single runs) and the LLM is non-deterministic | Several runs per scenario with pass rates, LLM-as-judge for tone/helpfulness, run in CI |
| Only Gemini was validated; other presets' default model names may be outdated | Run the eval suite per provider and pin tested models |
| Prompt-injection defense is prompt-based plus tool design (the LLM can't change prices) | Input/output filters and adversarial eval scenarios |
| Basic observability (Python logging) | Tracing of every LLM call and tool call (latency, cost, errors) |
| The API key in the UI is safe when running locally; if deployed, it passes through the hosting server | For a public deployment, keep keys server-side with user authentication |
| No streaming of responses | Stream tokens to the UI for a snappier chat |

---

## 8. Use of AI coding assistants

I used **Claude Code** (Anthropic's coding agent, inside VS Code) throughout the project, as a pair programmer. My workflow:

1. **Understanding and planning.**
   - Claude read the challenge PDF, the policy manual and all CSVs, and pointed out data inconsistencies (stock vs. status, conflicting phone numbers and installment rules, expired promotions in the challenge's own examples).
   - We turned that into a step-by-step plan where **each step is one commit**. I reviewed every step and made the commits myself.
2. **My decisions along the way:**
   - entering the API key in the UI instead of committing it, kept only in memory;
   - supporting any provider "as long as the user specifies it", which led to the OpenAI-compatible design;
   - writing all deliverables in English, as required by the recruiter's email;
   - asking whether the plan was really "the simplest way possible", which led to cutting the CLI and the database persistence;
   - keeping the evals ("simple, but not simplistic").
3. **Implementation.**
   - Claude wrote the code and the tests for each step. I reviewed the changes before committing.
   - Business rules were written test-first against the specific data cases found earlier (e.g. Takamine GD20's expired promotion).
4. **Validation with the real model.**
   - Running the agent against Gemini exposed problems no unit test could catch: a retired default model, an overloaded model, unbacked "I registered it" claims, invented shipping details, intermittent empty responses.
   - Each was diagnosed (e.g. inspecting raw API responses) and fixed, and the evals were re-run.
   - Claude also corrected one of its own earlier conclusions: a "store is closed" answer it had flagged as wrong was actually right, because Campo Grande is one hour behind Brasília.

**What worked well:** fast analysis of the data, a disciplined commit-per-step history, and a tight loop of test → run against the real LLM → fix.

**What required my attention:** keeping the scope lean, confirming the assumptions in the data quality report, and checking every sample conversation against the data before publishing it.
