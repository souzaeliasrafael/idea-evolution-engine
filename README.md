# Idea Evolution Engine

> Versão em português: [README.pt-BR.md](README.pt-BR.md)
>
> Documentation: [PROJECT_SPEC.md](PROJECT_SPEC.md) (architecture by phase) ·
> [PROVIDERS.md](PROVIDERS.md) (providers, models and costs) ·
> [PROJECT_RULES.md](PROJECT_RULES.md) (engineering rules)

Idea Evolution Engine (IEE) is designed to turn a raw idea into a traceable,
evidence-aware decision through a bounded, state-oriented workflow.

This repository implements **Phases 1 through 10 plus operational hardening**: the FastAPI foundation,
SQLite persistence, project APIs, per-agent model routing, a vendor-independent
`LLMProvider`, a deterministic mock provider, five individually executable
agents, deterministic scoring, persisted decisions, bounded workflow
orchestration, hypotheses, evidence, cost budgets, stagnation detection, and a
Next.js interface, human confirmation gates, experiments, reusable agent
profiles, reports, backup/restore, health diagnostics, cost observability,
browser E2E tests, CI, and production HTTP adapters for OpenAI, Anthropic,
Gemini, and OpenAI-compatible local services.

The **Opportunity Discovery** module can now start before a project exists. It
uses a founder profile and four bounded calls (web Scout, Idea Generator, web
Opportunity Researcher, and Portfolio Judge) to find current pain signals,
generate candidates, deduplicate and pre-screen them, research only the best
ones, and produce a comparable ranking. A selected candidate can be promoted
into the existing project evaluation workflow without losing its discovery
context.

The OpenAI Responses adapter sends each agent's Pydantic JSON Schema as a
strict Structured Output contract. Prompt instructions remain editable and
versioned independently from that protected output contract.

## Architecture

The implemented request path is:

```text
Next.js UI -> FastAPI router -> individual agent services -------------+
       |                                                               |
       +-> bounded Orchestrator -> Researcher -> Builder -> Critic
                    |                    ^           |          |
                    |                    +-- Researcher <-+     |
                    |                            |               |
                    +-> Round ------------> Builder -> Judge -> SQLAlchemy
                                                   |
                                                 SQLite
                                                   |
                         Hypotheses + Evidence <- LLMRouter -> LLMProvider
                                                   |
                                Human Review <-+-> Experiment
                                                   |
                                              Score Engine
```

HTTP contracts use Pydantic schemas. Project states use an explicit domain enum.
Alembic owns the application schema. Modules do not depend on any LLM vendor.
The implemented design and deferred risks are documented in
[`PROJECT_SPEC.md`](PROJECT_SPEC.md).

## Requirements

- Python 3.11 or newer
- Node.js 20.9 or newer
- Docker with Compose (optional)

## Local installation

From the repository root:

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment, then install the application and test tools:

```bash
python -m pip install -e ".[test]"
```

Copy `.env.example` to `.env` in the repository root if you want to override the
defaults. The settings loader also accepts environment variables directly.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `APP_NAME` | `Idea Evolution Engine` | API display name |
| `APP_ENV` | `development` | Runtime environment label |
| `LOG_LEVEL` | `INFO` | Structured log threshold |
| `DATABASE_URL` | `sqlite+aiosqlite:///./iee.db` | Async SQLAlchemy URL |
| `LLM_PROVIDER` | `mock` | Fallback adapter: `mock`, `openai`, `anthropic`, `gemini`, or an OpenAI-compatible alias |
| `LLM_MODEL` | `mock-llm-v1` | Fallback model name |
| `LLM_*_COST_PER_MILLION` | `0` | Fallback input, cached-input, and output token prices used for budget estimates |
| `<AGENT>_PROVIDER` | inherited | Provider for evaluation and development agents, including the four Blueprint roles |
| `<AGENT>_MODEL` | `mock-llm-v1` | Model for the corresponding agent |
| `<AGENT>_*_COST_PER_MILLION` | fallback | Per-agent input/cached-input/output price overrides |
| `RESEARCH_WEB_ENABLED` | `true` | Enables web research when the Researcher adapter supports it |
| `RESEARCH_WEB_MAX_CALLS` | `2` | Maximum web tool calls per Researcher attempt |
| `RESEARCH_WEB_CONTEXT_SIZE` | `low` | OpenAI web-search context size: `low`, `medium`, or `high` |
| `OPENAI_WEB_SEARCH_COST_PER_CALL` | `0.01` | Current estimated USD tool charge added to each OpenAI web search call |
| `LLM_MAX_ATTEMPTS` | `2` | Bounded validation attempts, from 1 to 3 |
| `LLM_RETRY_MAX_OUTPUT_TOKENS` | `16384` | Maximum adaptive output allowance after a truncated typed response |
| `BUILDER_MAX_OUTPUT_TOKENS` | `8192` | Builder allowance from its first and only truncation-sensitive attempt |
| `ADAPTIVE_AGENT_DEPTH_ENABLED` | `true` | Treat per-project depth as a ceiling and start each stage with one call |
| `MAX_ROUNDS` | `5` | Hard server-side ceiling for one orchestrator invocation |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Browser origin permitted by CORS |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | API base URL compiled into the frontend |
| `OPENAI_ADMIN_KEY` | empty | Optional organization admin key used only to reconcile OpenAI billing |
| `OPENAI_BILLING_PROJECT_IDS` | empty | Optional comma-separated OpenAI project IDs used to filter reconciliation |

Each agent can use a different provider and model without frontend changes. The
generic `LLM_*` pair is used only when an agent-specific value is omitted. No API
credential is used by the built-in mock. Real credentials must remain in
environment variables and must never be committed. See
[`PROVIDERS.md`](PROVIDERS.md) for the adapter extension point and safe setup.
Cloud adapters require their server-side API key and explicit input/output token
prices. This prevents a configured project budget from silently running with
unknown zero cost. Local OpenAI-compatible services may intentionally use zero
pricing.

## Run the backend

From `backend/`:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the generated API documentation.

## API

### Discover opportunities before creating a project

Open `http://localhost:3000/discover`, save a founder profile, and create a
campaign with its own USD budget and explicit hard constraints. New campaigns
generate only three to five candidates, research at most the strongest subset,
and record every call, token count, web-search charge, source URL, intermediate
candidate, axis score, confidence, and validation plan. It performs at most four agent stages and never starts the
normal multi-round project workflow automatically.

The backend enforces customer type, digital/self-service delivery, minimum
automation, maximum MVP time, recurring human work, regulated advice, two-sided
marketplaces, revenue repetition, and channel requirements. A failing candidate
is stopped before deeper research. Researched candidates receive a deterministic
**Market Reality Score** based on demand, willingness to pay, paid competitors,
acquisition, recurrence, margin, and evidence quality. Only candidates that meet
the source, competitor, channel, and score gates reach the Portfolio Judge.

The discovery agents reuse the existing model profile safely:

- Opportunity Scout and Opportunity Researcher use the configured `RESEARCHER`.
- Idea Generator uses the configured `STRUCTURER`.
- Portfolio Judge uses the configured `JUDGE`.

After ranking, **Transformar em projeto** creates a normal project with the
selected research embedded as initial context. Its budget is independent from
the discovery campaign budget.

Each opportunity also accepts explicit founder feedback. **Aprovar** marks a
pattern worth deepening. **Não gostei** accepts reusable reason tags and an
optional note. New campaigns receive a compact, profile-scoped memory of prior
ideas, research sources, scores and feedback. The campaign chooses one policy:
only novel ideas, a balanced mode that suppresses rejected/duplicate patterns,
or improvements derived from approved ideas. Deterministic similarity screening
still runs after generation, so prompt compliance is not the only safeguard.
Rejection-tag frequencies are also supplied to the Judge and become bounded,
deterministic ranking penalties when the same conflict reappears.

Every candidate has a commercial-validation form for landing-page or offer
results: visits, leads, preorders, paying customers, revenue, and acquisition
spend. A positive validation requires at least one preorder or paying customer
and records explicit deltas for overall score, confidence, and Market Reality.
Research-only candidates without direct purchase evidence have confidence capped
at 35%; observed purchase evidence can unlock promotion even when the original
research gate was inconclusive.

The four discovery prompts also appear on the existing **Prompts** page. Saving
one creates an immutable custom version; resetting restores the packaged `v1`
without deleting its history. A campaign records the exact prompt version used.

Create a project:

```bash
curl -X POST http://127.0.0.1:8000/projects \
  -H "Content-Type: application/json" \
  -d '{"name":"Traceable product discovery","raw_idea":"Evaluate ideas before implementation."}'
```

An optional `max_ai_budget` can be supplied at creation and changed later:

```bash
curl -X PATCH http://127.0.0.1:8000/projects/PROJECT_UUID/budget \
  -H "Content-Type: application/json" \
  -d '{"max_ai_budget":"2.500000"}'
```

Pass `null` to remove the limit. Every provider response contributes its
`estimated_cost`, including invalid attempts. Once accumulated cost reaches the
configured ceiling, no new LLM call starts; an already completed call remains
audited and the workflow reports `BUDGET_LIMIT_REACHED`.

List and retrieve projects:

```bash
curl http://127.0.0.1:8000/projects
curl http://127.0.0.1:8000/projects/PROJECT_UUID
```

Create and inspect the immutable initial version:

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/structure
curl http://127.0.0.1:8000/projects/PROJECT_UUID/versions
```

Run Builder or Critic independently:

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/builder
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/critic
```

The project must first have V0 from `/structure`. Builder creates the next
immutable version. Critic records falsifiable criticisms against the current
version without changing it. Neither endpoint starts another agent or a loop.

Run Judge and inspect its persisted score and decision independently:

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/judge
curl http://127.0.0.1:8000/projects/PROJECT_UUID/scores
curl http://127.0.0.1:8000/projects/PROJECT_UUID/decisions
```

Judge requires a structured project, but does not invoke Builder, Critic, or an
Orchestrator. It returns a typed decision, a deterministic score from 0 to 100,
confidence, blockers, unknowns, next actions, and the complete score breakdown.
The LLM supplies criterion ratings and reasoning; the application computes the
weighted score and enforces approval safeguards.

Run Improver independently after at least one Judge assessment:

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/improver
curl http://127.0.0.1:8000/projects/PROJECT_UUID/improvement-plans
```

Improver diagnoses weak criteria and produces evidence-aware proposals,
Builder instructions, Researcher questions, validation steps, and stop
conditions. It cannot change the score or confidence. Its typed plan is linked
to the source score and decision and becomes context for the next round.

Run Researcher independently and manage the traceable knowledge layer:

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/researcher
curl http://127.0.0.1:8000/projects/PROJECT_UUID/hypotheses
curl http://127.0.0.1:8000/projects/PROJECT_UUID/evidence
```

Hypotheses can also be created and updated through `POST
/projects/{id}/hypotheses` and `PATCH
/projects/{id}/hypotheses/{hypothesis_id}`. Evidence is added through `POST
/projects/{id}/evidence`. Hypothesis priority is calculated as `impact × (1 −
confidence)`, and evidence remains linked to its hypothesis by stable `H...` and
`E...` references.

Run the bounded workflow and inspect its rounds:

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/run \
  -H "Content-Type: application/json" \
  -d '{"max_rounds":3}'
curl http://127.0.0.1:8000/projects/PROJECT_UUID/rounds
curl http://127.0.0.1:8000/projects/PROJECT_UUID/timeline
curl http://127.0.0.1:8000/projects/PROJECT_UUID/criticisms
```

The body is optional and defaults to three rounds. `MAX_ROUNDS` defaults to five
and rejects larger requests before any LLM call. The Orchestrator creates V0 when
needed, then runs the configured number of Builder, Researcher, and Critic calls
before Judge. After a non-terminal judgment, Improver creates the plan consumed
by the next round. Each optional agent can run from zero to three times per round;
Structurer, Judge, and Improver remain automatic. `REFINE`,
`RESEARCH` continues while capacity remains. `PIVOT`, `APPROVE`, and `DISCARD`
pause in `AWAITING_CONFIRMATION`; a person must accept, continue anyway, or issue
a manual pivot instruction. `TEST` creates a persisted experiment and pauses until
that experiment is completed or cancelled. Failed Researcher, Builder, or
Critic stages are preserved as warnings and the round continues from valid
persisted state. Structurer and Judge remain critical stages. Truncated typed
responses retry with a larger bounded output allowance and validation feedback.
Three consecutive score improvements below three points mark the project as
stagnant. Subsequent Judge runs reject another `REFINE` decision and require a
more meaningful next step.

The default mock makes local development deterministic. Its concept is explicitly
provisional and must not be treated as research or evidence.

### Text and voice conversation with the Judge

The project page includes **Converse com o Judge**. A submitted message is saved
as human context and runs exactly one complete workflow round before returning
the new Judge decision, score, confidence, blocker, and recommended next step.
The same budget, human-review, experiment, live-progress, and safe-cancellation
rules used by the regular Orchestrator remain active.

The primary **Iniciar conversa natural** mode uses an OpenAI Realtime WebRTC
session with semantic turn detection, the `marin` neural voice, and automatic
interruption. Every substantive utterance calls the existing persisted Judge
chat endpoint, so the model cannot invent a decision outside the full workflow.
The standard API key never reaches the browser: the backend mints a short-lived
client secret after checking project budget and workflow blockers. Sessions are
limited to ten minutes by default.

Realtime audio is API usage separate from the agent-cycle cost and does not use
a ChatGPT subscription. Agent calls remain charged to the project budget; audio
cost appears in provider reconciliation but is not currently assigned to the
project total. The compatible text/transcription mode remains available and can
use the browser's native Portuguese speech features without opening a Realtime
session. Conversation turns are persisted, exported in backups, and included in
project reports.

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/judge-chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Considere também clientes públicos. Isso muda a avaliação?","input_mode":"TEXT"}'
curl http://127.0.0.1:8000/projects/PROJECT_UUID/judge-chat
```

## Optional development blueprint

After a project has a structured concept, `POST
/projects/{id}/development-blueprints` runs a separate bounded pipeline: Product
Architect, one to three Solution Architect alternatives, Technical Critic, and
Roadmap Planner. It consumes the concept, Researcher outputs, evidence,
criticisms, and decisions, then persists requirements, architecture options,
technical review, delivery phases, backlog, testing, security, deployment,
observability, and traceability. It does not generate experiments or application
code. Each call remains visible in the timeline and financial panel.

### Human review and experiments

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/decisions/DECISION_UUID/review \
  -H "Content-Type: application/json" \
  -d '{"action":"ACCEPT_RECOMMENDATION","note":"Reviewed by the product owner"}'

curl http://127.0.0.1:8000/projects/PROJECT_UUID/experiments
curl -X PATCH http://127.0.0.1:8000/projects/PROJECT_UUID/experiments/EXPERIMENT_UUID \
  -H "Content-Type: application/json" \
  -d '{"status":"COMPLETED","success_metric":"Paid pilots","success_threshold":"2","outcome":"SUCCESS","result_summary":"Three signed pilots","observed_value":"3 letters","sample_size":5,"methodology":"Five structured interviews using one script"}'

curl -X POST http://127.0.0.1:8000/projects/PROJECT_UUID/experiments/EXPERIMENT_UUID/reassess
```

Human actions are `ACCEPT_RECOMMENDATION`, `CONTINUE_ANYWAY`, and
`MANUAL_PIVOT`. Manual pivot requires a note and supplies it to Builder on the
next bounded run. Completing an experiment automatically scores its evidence
quality from 0 to 5, infers the affected score criteria, creates a linked
`EXPERIMENT` evidence record, and updates the linked hypothesis. Saving never
starts an AI call: the focused Judge reassessment is an explicit second action
through the endpoint above or the **Reavaliar com esta evidência** button. It
does not replay the full multi-agent workflow and stores score and confidence
before and after. If the Judge fails or the AI budget is exhausted, the
experiment and evidence remain safely persisted and can be reassessed later.
Planned, running, and cancelled experiments never count as validating evidence.

### Profiles, diagnostics, reports, and backups

- `POST/GET/PUT/DELETE /agent-profiles` manages reusable per-agent provider,
  model, and price configurations. Profiles never contain API keys.
- `GET/PUT/DELETE /agent-prompts/{agent}` lists, versions, and restores the
  global prompt for each agent. `GET /agent-prompts/{agent}/versions` exposes
  its immutable custom history. Restoring the default deactivates overrides
  without deleting that history.
- `PATCH /projects/{id}/agent-profile` attaches or removes a profile.
- `PATCH /projects/{id}/agent-plan` selects zero to three calls per workflow
  stage. Builder and Researcher each have two stages per round; Critic has one.
  At least one of these agents must remain enabled.
- `GET /projects/{id}/run-status` reports the active agent and round while a
  bounded workflow request is running; it never triggers an LLM call.
- `PATCH /projects/{id}/budget` remains available during a workflow. The active
  provider request keeps its original boundary, while every following agent
  reloads the persisted project ceiling before it may start another paid call.
- Discovery campaigns also recover safely after a local server restart: a
  `RUNNING` row without a live request becomes resumable instead of remaining
  indefinitely active, and cancelling such an orphan completes immediately.
- `POST /projects/{id}/run-cancel` requests a safe stop. The in-flight agent is
  cancelled immediately, which closes the active provider HTTP request; the
  round is then marked `CANCELLED`. The request and heartbeat live in the
  database, so cancellation also works across API workers and stale executions
  are released after a process restart, including any round left `RUNNING` by
  the terminated process.
- `GET /health`, `GET /ready`, and `GET /system/config` expose safe diagnostics;
  configuration output contains booleans, never credential values.
- `GET /projects/{id}/metrics` aggregates calls, tokens, time, failures, and cost
  by agent and model.
- `GET /projects/{id}/efficiency` compares each round's context size, calls,
  tokens, cache, cost, score/confidence deltas, and cost per score point.
- `GET /projects/{id}/report` and `GET /projects/{id}/report.md` export the full
  evaluation as typed JSON or downloadable Markdown.
- `GET /projects/{id}/backup` creates a portable JSON snapshot and `POST
  /projects/import` restores it with new identifiers.

### Financial panel and billing reconciliation

Open `http://localhost:3000/finance` to compare two intentionally separate
numbers:

- **Estimated cost** is calculated immediately from each profile's input/output
  token prices. For OpenAI web research it also includes the configured cost per
  search call. It is stored per agent run and is the value that enforces each
  idea's budget before another model call starts.
- **Reconciled cost** comes from a provider billing API or a manual entry. It is
  authoritative for invoice review, but provider-wide totals are not assigned to
  an internal idea unless the provider supplies a reliable mapping.

The dashboard groups estimated usage by provider, model, agent, project, and
day. It also displays cached-input and reasoning token counters when a provider
returns them, provider connectors, synchronization history, unpriced runs,
budget status, and recent billing entries.

The Researcher uses the OpenAI Responses API web-search tool when its provider
is `openai`. Consulted URLs are stored as neutral, traceable evidence and shown
on the project screen. The timeline separates token usage, search-call count,
tool cost, and the combined estimate.

The regular `OPENAI_API_KEY` executes model requests. OpenAI organization cost
reconciliation is a separate administrative operation and therefore requires an
optional `OPENAI_ADMIN_KEY` in the root `.env`:

```dotenv
OPENAI_ADMIN_KEY=<organization-admin-key>
# Optional: restrict billing imports to these OpenAI projects.
OPENAI_BILLING_PROJECT_IDS=proj_example,proj_other
```

Restart the backend after changing either variable, then use **Financeiro →
Sincronizar**. The admin key never leaves the backend. Other providers work
immediately through manual USD entries and can later gain automatic
reconciliation through the billing adapter interface described in
[`PROVIDERS.md`](PROVIDERS.md).

## Tests

From `backend/`:

```bash
pytest
```

Tests use an isolated in-memory SQLite database and never call external APIs.
To verify the migration independently:

```bash
alembic upgrade head
alembic current
```

Frontend checks and the real browser workflow run from `frontend/`:

```bash
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

The Playwright configuration starts both applications, migrates a disposable
SQLite database, submits an idea through the UI, and verifies the resulting
project screen. `.github/workflows/ci.yml` runs backend, frontend, and E2E jobs.

## Docker

From the repository root:

```bash
docker compose up --build
```

The interface is available on port 3000 and the API on port 8000. The SQLite file
is stored in the named Docker volume `iee_data`.

## Frontend

From `frontend/`:

```bash
npm install
npm run dev
```

Open `http://localhost:3000`. The interface provides a project dashboard, idea
creation with optional profile, per-agent depth, and AI budget, bounded evaluation, human decision
controls, experiment result forms, project status and cost controls, current
concept, critical problems, prioritized hypotheses, decisions, per-agent metrics,
downloadable reports/backups, restore, chronological agent history, and a
persisted text/voice conversation with the Judge.
During a bounded run, the project screen polls the safe run-status endpoint and
shows the active round and agent in real time without making additional LLM calls.
Its **Stop execution** action cancels the task and interrupts the active
provider request. The same control is available while
the first evaluation is running on the new-idea page. Completed calls remain
recorded; the interrupted round is closed safely.
The **Profiles** page creates and edits reusable provider, model, and token-price
settings independently for every agent. New profiles can copy the server's
safe defaults without exposing API keys. A profile can be selected or removed
from an existing project in its **Operation** panel; the change affects only
future agent calls.
The same panel controls **Focus per round** independently from the provider
profile: zero disables Builder, Researcher, or Critic, while two or three calls
deepen that specialist's contribution. Builder and Researcher occur twice in
each round, so their configured depth is applied twice. Extra calls consume the
same project AI budget and are stopped by its configured ceiling.
The **Prompts** page edits every agent, including Improver, independently.
Changes apply only to future calls, and each save creates a new
auditable prompt version while the backend continues to enforce typed schemas.

## Agent workflow

The implemented workflow is bounded to at most three rounds by default:

```text
User Idea -> Structurer -> Researcher -> Builder -> Critic
          -> Researcher -> Builder -> Judge -> Improver -> decision
```

Each output is appended to a structured round memory before the next agent runs.
The second Researcher verifies the Critic's objections, the final Builder applies
the verified findings, and Judge receives the entire ordered round memory plus
the persistent concept, hypotheses, evidence, criticisms, scores, and decisions.
Improver then converts that assessment into a bounded plan for the next round.

Structurer, Builder, Researcher, Critic, Judge, and Improver are implemented as individually
invoked agents and can also be run through the bounded Orchestrator. Every agent
depends only on `LLMProvider`, never on an LLM SDK, and loads a versioned prompt
from its own directory under `prompts/`. `LLMRouter` selects the configured adapter
and model for each agent.

## Database

The database contains `projects`, immutable `idea_versions`, `rounds`,
`agent_runs`, `hypotheses`, `evidence`, `criticisms`, `scores`, `decisions`,
`judge_chat_turns`, `improvement_plans`, `experiments`, `development_blueprints`,
and `agent_profiles`.
Projects carry the per-agent execution plan, accumulated/model budget values,
and stagnation state; rounds record
budget stops and stagnation snapshots.
Knowledge records retain their epistemic classification and evidence linkage.
Criticisms, scores, and decisions remain linked to the idea version and successful
agent run that produced them. Each orchestrated AgentRun links to its Round;
independently run agents retain a nullable round link. Every schema change must be
introduced through a new Alembic migration.

## Roadmap

1. Completed — Phase 1 project API and persistence foundation.
2. Completed — Phase 2 provider abstraction, Structurer, V0, prompt versioning,
   typed validation, bounded retry, and run persistence.
3. Completed — Phase 3 individually executable Builder and Critic.
4. Completed — Phase 4 per-agent model routing, Score Engine, Judge, and Decision.
5. Completed — Phase 5 bounded Orchestrator, Round, and explicit transitions.
6. Completed — Phase 6 hypothesis register, evidence ledger, and Researcher.
7. Completed — Phase 7 cost tracking, project budgets, automatic budget stops,
   and stagnation detection.
8. Completed — Phase 8 Next.js dashboard, new-idea flow, and complete project
   inspection screen.
9. Completed — Phase 9 explicit human confirmation and auditable overrides.
10. Completed — Phase 10 typed experiment planning, results, and Judge context.
11. Completed — operational hardening with reusable profiles, health/readiness,
    per-agent metrics, report/backup export, restoration, browser E2E, and CI.
12. Completed — typed post-Judge Improver, persisted improvement plans, manual
    execution, and automatic reuse by subsequent rounds.
13. Completed — persisted Judge conversation with browser voice input/output,
    one-round orchestration, live progress, cancellation, reports, and backups.
14. Completed — natural full-duplex Judge voice through OpenAI Realtime, semantic
    end-of-turn detection, interruption, secure ephemeral credentials, and a
    browser-speech fallback.
15. Completed — durable multi-worker cancellation, partial Builder recovery,
    round-efficiency dashboard, historical cache repricing, and blind per-agent
    model quality/cost screening.

## Cost maintenance and model screening

Cached-token repricing is idempotent and can update one project or every
historical project:

```bash
python tools/reprice_cached_tokens.py --all-projects
python tools/reprice_cached_tokens.py --all-projects --apply
```

Before assigning a cheaper model to an agent, run the non-mutating blind screen
against the latest successful historical case of every central agent:

```bash
python tools/evaluate_agent_models.py --project-id <uuid> --candidate-model gpt-5-nano
```

The report is stored under `backend/work/agent-model-evals/`. Experimental calls
do not alter project history, score, profile, or budget. A candidate is only
marked for a profile trial when it costs less and its blind quality score is no
more than three points below the recorded baseline.
