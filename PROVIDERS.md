# Provider and model configuration

The backend chooses an adapter, model, and token pricing independently for each
agent. Credentials remain in server environment variables and are never sent to
the frontend or persisted in `AgentRun`.

## Built-in adapters

| Provider value | API contract | Credential |
|---|---|---|
| `mock` | Deterministic offline test provider | None |
| `openai` | OpenAI Responses API | `OPENAI_API_KEY` |
| `anthropic` | Anthropic Messages API | `ANTHROPIC_API_KEY` |
| `gemini` | Gemini `generateContent` API | `GEMINI_API_KEY` |
| `openai-compatible` | `/chat/completions` compatible service | Optional `OPENAI_COMPATIBLE_API_KEY` |

`openai_compatible`, `compatible`, and `local` are aliases for
`openai-compatible`. The local default is `http://localhost:11434/v1`, suitable
for a service that exposes an OpenAI-compatible endpoint. Change
`OPENAI_COMPATIBLE_BASE_URL` for another local or hosted implementation.

The adapters use direct async HTTP calls, normalize provider output to
`LLMResponse`, record input/output tokens, and calculate `estimated_cost`. The
agent layer remains vendor-independent.

Reusable configurations can also be persisted through `/agent-profiles`. A
profile stores only provider names, model identifiers, and token prices. Keys
remain exclusively in server environment variables. Attaching a profile to a
project makes individual and orchestrated calls use that profile.

## Configure agents independently

Copy `.env.example` to `.env`. This example deliberately uses placeholders for
model IDs and prices because they depend on your account, region, model version,
and current provider pricing:

```dotenv
STRUCTURER_PROVIDER=openai
STRUCTURER_MODEL=<your-openai-model>
STRUCTURER_INPUT_COST_PER_MILLION=<current-input-price>
STRUCTURER_CACHED_INPUT_COST_PER_MILLION=<current-cached-input-price>
STRUCTURER_OUTPUT_COST_PER_MILLION=<current-output-price>

BUILDER_PROVIDER=anthropic
BUILDER_MODEL=<your-anthropic-model>
BUILDER_INPUT_COST_PER_MILLION=<current-input-price>
BUILDER_OUTPUT_COST_PER_MILLION=<current-output-price>

RESEARCHER_PROVIDER=gemini
RESEARCHER_MODEL=<your-gemini-model>
RESEARCHER_INPUT_COST_PER_MILLION=<current-input-price>
RESEARCHER_OUTPUT_COST_PER_MILLION=<current-output-price>

CRITIC_PROVIDER=local
CRITIC_MODEL=<your-local-model>
CRITIC_INPUT_COST_PER_MILLION=0
CRITIC_OUTPUT_COST_PER_MILLION=0

JUDGE_PROVIDER=openai
JUDGE_MODEL=<your-openai-model>
JUDGE_INPUT_COST_PER_MILLION=<current-input-price>
JUDGE_OUTPUT_COST_PER_MILLION=<current-output-price>

# Optional override. If omitted, Improver inherits Builder.
IMPROVER_PROVIDER=openai
IMPROVER_MODEL=<your-openai-model>
IMPROVER_INPUT_COST_PER_MILLION=<current-input-price>
IMPROVER_OUTPUT_COST_PER_MILLION=<current-output-price>

# Optional overrides. If omitted, Product/Solution Architect inherit Builder,
# Technical Critic inherits Critic, and Roadmap Planner inherits Judge.
PRODUCT_ARCHITECT_PROVIDER=openai
PRODUCT_ARCHITECT_MODEL=<your-openai-model>
SOLUTION_ARCHITECT_PROVIDER=openai
SOLUTION_ARCHITECT_MODEL=<your-openai-model>
TECHNICAL_CRITIC_PROVIDER=anthropic
TECHNICAL_CRITIC_MODEL=<your-anthropic-model>
ROADMAP_PLANNER_PROVIDER=openai
ROADMAP_PLANNER_MODEL=<your-openai-model>

OPENAI_API_KEY=<secret>
# Optional natural Judge voice settings (OpenAI Realtime API)
VOICE_REALTIME_ENABLED=true
VOICE_REALTIME_MODEL=gpt-realtime-2.1
VOICE_REALTIME_VOICE=marin
VOICE_REALTIME_MAX_SESSION_SECONDS=600
ANTHROPIC_API_KEY=<secret>
GEMINI_API_KEY=<secret>
OPENAI_COMPATIBLE_BASE_URL=http://localhost:11434/v1
```

`LLM_PROVIDER`, `LLM_MODEL`, `LLM_INPUT_COST_PER_MILLION`,
`LLM_CACHED_INPUT_COST_PER_MILLION`, and `LLM_OUTPUT_COST_PER_MILLION` are global fallbacks. An agent-specific value takes
precedence. Restart the backend after changing configuration because the router
is cached per process.

## Cost safety

Cloud adapters fail configuration when both token prices are zero. This protects
project budgets from silently treating paid calls as free. Update the prices from
the provider's current pricing page. If a cloud model is genuinely free or cost
tracking is intentionally disabled, set:

```dotenv
ALLOW_UNPRICED_CLOUD_MODELS=true
```

The engine computes:

```text
((input_tokens - cached_tokens) × input_price
 + cached_tokens × cached_input_price
 + output_tokens × output_price) / 1,000,000
```

The result is rounded to six decimal places, accumulated on the project, and
checked before the next agent call. Provider-side charges remain authoritative;
the engine value is an estimate for workflow control.

For OpenAI-backed Researcher runs, the adapter can also invoke the Responses API
web-search tool. Configure its bound and estimated charge independently:

```dotenv
RESEARCH_WEB_ENABLED=true
RESEARCH_WEB_MAX_CALLS=2
RESEARCH_WEB_CONTEXT_SIZE=low
OPENAI_WEB_SEARCH_COST_PER_CALL=0.01
```

The combined run estimate is token cost plus actual web-search calls multiplied
by the configured per-call price. Search content included in provider token
usage is therefore charged through the normal input/output formula, while the
tool fee remains visible separately. Other adapters opt into this capability by
implementing `supports_web_search` and mapping the generic `WebSearchConfig`.

## Billing adapters and the financial panel

Execution adapters and billing adapters are deliberately independent. An
`LLMProvider` runs an agent and returns token usage immediately; a
`BillingProviderAdapter` imports authoritative costs later. This lets every
agent use a different model while keeping budget enforcement fast and invoice
reconciliation honest.

The built-in OpenAI billing adapter calls the organization costs endpoint with
daily buckets and groups by provider project, API key ID, and line item. It uses
an administrative key separate from `OPENAI_API_KEY`:

```dotenv
OPENAI_ADMIN_KEY=<organization-admin-key>
OPENAI_BILLING_PROJECT_IDS=proj_optional_filter
```

Without the admin key, agent execution continues normally and the dashboard
still shows estimates. Anthropic, Gemini, local models, and future providers can
be recorded manually from `/finance` until an automatic connector is added.

To add one, implement `BillingProviderAdapter` under `backend/app/billing/` and
register it during backend startup:

```python
from app.billing.dependencies import register_billing_adapter


register_billing_adapter(ExampleBillingAdapter(...))
```

The adapter returns normalized `BillingCostItem` records. Stable period and
grouping fields make repeated synchronization idempotent; credentials remain in
backend environment variables. The relevant endpoints are:

- `GET /finance/overview?days=30`
- `POST /finance/sync/{provider}` with `{"days": 30}`
- `POST /finance/costs/manual`

## Endpoint and runtime settings

```dotenv
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_VERSION=2023-06-01
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
OPENAI_COMPATIBLE_BASE_URL=http://localhost:11434/v1
LLM_REQUEST_TIMEOUT_SECONDS=120
LLM_MAX_OUTPUT_TOKENS=4096
LLM_RETRY_MAX_OUTPUT_TOKENS=16384
BUILDER_MAX_OUTPUT_TOKENS=8192
```

OpenAI uses `/responses`; Anthropic uses `/v1/messages`; Gemini uses
`/models/{model}:generateContent`; compatible services use `/chat/completions`.
Only the compatible base URL should normally be changed to a non-official host.

## Add another adapter

Implement `LLMProvider` under `backend/app/llm/providers/` and register a factory.
Factories receive the resolved agent configuration, including model and prices:

```python
from app.llm.dependencies import register_provider_adapter
from app.llm.router import AgentModelConfig


def build_example(config: AgentModelConfig):
    return ExampleProvider(
        model_name=config.model,
        input_price=config.input_cost_per_million,
        output_price=config.output_cost_per_million,
    )


register_provider_adapter("example", build_example)
```

The registry rejects blank, duplicate, and unknown provider names. Do not log API
keys, include them in exception text, return them through HTTP schemas, or commit
the `.env` file.

## Official API references

- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Anthropic Messages API](https://platform.claude.com/docs/en/build-with-claude/working-with-messages)
- [Gemini generateContent API](https://ai.google.dev/api/generate-content)
