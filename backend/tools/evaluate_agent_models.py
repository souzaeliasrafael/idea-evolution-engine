"""Blind quality-and-cost screen for a cheaper model on historical agent inputs.

The project is read-only. Candidate generations and grader results are written
only to an evaluation report, never into project history or its AI budget.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import random
import sqlite3
import sys
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.base import AgentExecutionError, TypedAgent
from app.agents.builder import BuilderAgent
from app.agents.critic import CriticAgent
from app.agents.improver import ImproverAgent
from app.agents.judge import JudgeAgent
from app.agents.researcher import ResearcherAgent
from app.agents.structurer import IdeaStructurer
from app.core.config import get_settings
from app.domain.enums import AgentType
from app.llm.base import LLMProvider, LLMRequest, WebSearchConfig
from app.llm.dependencies import get_provider_registry
from app.llm.prompts import load_default_prompt
from app.llm.router import AgentModelConfig, config_for_agent


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "iee.db"
DEFAULT_OUTPUT_DIRECTORY = BACKEND_ROOT / "work" / "agent-model-evals"
CORE_AGENTS = (
    AgentType.STRUCTURER,
    AgentType.RESEARCHER,
    AgentType.BUILDER,
    AgentType.CRITIC,
    AgentType.IMPROVER,
    AgentType.JUDGE,
)


class QualityScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_fulfilment: Annotated[int, Field(ge=0, le=20)]
    factual_discipline: Annotated[int, Field(ge=0, le=20)]
    completeness: Annotated[int, Field(ge=0, le=20)]
    actionability: Annotated[int, Field(ge=0, le=20)]
    concision_and_clarity: Annotated[int, Field(ge=0, le=20)]

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())


class BlindAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_a: QualityScore
    output_b: QualityScore
    preferred_output: Literal["A", "B", "TIE"]
    reasons: Annotated[list[str], Field(min_length=1, max_length=3)]
    limitations: Annotated[list[str], Field(max_length=3)]


GRADER_PROMPT = """Compare two outputs for the same typed agent task. The order is
blind. Do not reward verbosity. Score each output 0-20 on task fulfilment,
factual discipline (no invented evidence), completeness of decisive fields,
actionability, and concise clarity. Respect the agent role supplied in the
input. Prefer the higher-quality output; use TIE when practically equivalent.
Return only strict JSON matching the schema."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--candidate-model", default="gpt-5-nano")
    parser.add_argument("--candidate-input-rate", default="0.05")
    parser.add_argument("--candidate-cached-input-rate", default="0.005")
    parser.add_argument("--candidate-output-rate", default="0.40")
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--seed", type=int, default=20260919)
    return parser.parse_args()


def _load_cases(database: Path, project_id: str) -> dict[AgentType, dict[str, Any]]:
    placeholders = ",".join("?" for _ in CORE_AGENTS)
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            f"""
            SELECT id, agent, input_json, output_json, model, estimated_cost, created_at
            FROM agent_runs
            WHERE project_id = ? AND error IS NULL AND output_json IS NOT NULL
              AND agent IN ({placeholders})
            ORDER BY created_at DESC, id DESC
            """,
            (project_id, *(agent.value for agent in CORE_AGENTS)),
        ).fetchall()
    cases: dict[AgentType, dict[str, Any]] = {}
    for run_id, agent_name, input_json, output_json, model, cost, created_at in rows:
        agent = AgentType(agent_name)
        if agent in cases:
            continue
        cases[agent] = {
            "run_id": str(run_id),
            "input": json.loads(input_json),
            "baseline_output": json.loads(output_json),
            "baseline_model": str(model),
            "baseline_cost": str(cost),
            "created_at": str(created_at),
        }
    return cases


def _load_prompt(database: Path, agent: AgentType) -> tuple[str, str]:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT content, version FROM agent_prompt_versions
            WHERE agent = ? AND is_active = 1
            ORDER BY version DESC, id DESC LIMIT 1
            """,
            (agent.value,),
        ).fetchone()
    if row:
        return str(row[0]), f"custom-v{row[1]}"
    return load_default_prompt(agent)


def _agent(
    agent_type: AgentType,
    provider: LLMProvider,
    *,
    prompt: str,
    version: str,
) -> TypedAgent[Any]:
    kwargs = {"prompt": prompt, "prompt_version": version, "max_attempts": 2}
    if agent_type == AgentType.STRUCTURER:
        return IdeaStructurer(provider, **kwargs)
    if agent_type == AgentType.BUILDER:
        return BuilderAgent(provider, **kwargs)
    if agent_type == AgentType.RESEARCHER:
        settings = get_settings()
        web_search = (
            WebSearchConfig(
                max_calls=settings.research_web_max_calls,
                context_size=settings.research_web_context_size,
            )
            if settings.research_web_enabled
            else None
        )
        return ResearcherAgent(provider, web_search=web_search, **kwargs)
    if agent_type == AgentType.CRITIC:
        return CriticAgent(provider, **kwargs)
    if agent_type == AgentType.IMPROVER:
        return ImproverAgent(provider, **kwargs)
    if agent_type == AgentType.JUDGE:
        return JudgeAgent(provider, **kwargs)
    raise ValueError(f"Unsupported eval agent: {agent_type.value}")


async def _candidate_output(
    agent_type: AgentType,
    provider: LLMProvider,
    case: dict[str, Any],
    database: Path,
) -> dict[str, Any]:
    prompt, version = _load_prompt(database, agent_type)
    agent = _agent(agent_type, provider, prompt=prompt, version=version)
    try:
        result = await agent.execute(case["input"])
    except AgentExecutionError as exc:
        responses = [item.response for item in exc.attempts if item.response]
        return {
            "succeeded": False,
            "output": None,
            "error": exc.attempts[-1].error if exc.attempts else "unknown",
            "cost": str(sum((item.estimated_cost for item in responses), Decimal("0"))),
            "input_tokens": sum(item.input_tokens for item in responses),
            "output_tokens": sum(item.output_tokens for item in responses),
        }
    responses = [item.response for item in result.attempts if item.response]
    return {
        "succeeded": True,
        "output": result.output.model_dump(mode="json"),
        "error": None,
        "cost": str(sum((item.estimated_cost for item in responses), Decimal("0"))),
        "input_tokens": sum(item.input_tokens for item in responses),
        "output_tokens": sum(item.output_tokens for item in responses),
    }


async def _grade(
    provider: LLMProvider,
    agent: AgentType,
    context: dict[str, Any],
    output_a: dict[str, Any],
    output_b: dict[str, Any],
) -> tuple[BlindAssessment, dict[str, Any]]:
    response = await provider.generate(
        LLMRequest(
            role="AGENT_MODEL_EVALUATOR",
            prompt=GRADER_PROMPT,
            input_data={
                "agent_role": agent.value,
                "task_context": context,
                "output_a": output_a,
                "output_b": output_b,
            },
            output_schema_name="agent_model_blind_assessment",
            output_schema=BlindAssessment.model_json_schema(),
            max_output_tokens=2048,
        )
    )
    return BlindAssessment.model_validate_json(response.content), {
        "model": response.model,
        "cost": str(response.estimated_cost),
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
    }


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    database = args.database.resolve()
    cases = _load_cases(database, args.project_id)
    settings = get_settings()
    registry = get_provider_registry()
    candidate = registry.create(
        AgentModelConfig(
            provider="openai",
            model=args.candidate_model,
            input_cost_per_million=Decimal(args.candidate_input_rate),
            cached_input_cost_per_million=Decimal(args.candidate_cached_input_rate),
            output_cost_per_million=Decimal(args.candidate_output_rate),
        )
    )
    grader = registry.create(config_for_agent(settings, AgentType.JUDGE))
    rng = random.Random(args.seed)
    results: list[dict[str, Any]] = []
    for agent_type in CORE_AGENTS:
        case = cases.get(agent_type)
        if case is None:
            results.append({"agent": agent_type.value, "status": "NO_HISTORICAL_CASE"})
            continue
        candidate_result = await _candidate_output(
            agent_type, candidate, case, database
        )
        record: dict[str, Any] = {
            "agent": agent_type.value,
            "status": "CANDIDATE_FAILED" if not candidate_result["succeeded"] else "GENERATED",
            "source_run_id": case["run_id"],
            "baseline_model": case["baseline_model"],
            "baseline_cost": case["baseline_cost"],
            "candidate_model": args.candidate_model,
            "candidate": candidate_result,
        }
        if not candidate_result["succeeded"]:
            record["recommendation"] = "KEEP_BASELINE"
            results.append(record)
            continue
        candidate_label = "A" if rng.choice((True, False)) else "B"
        output_a = candidate_result["output"] if candidate_label == "A" else case["baseline_output"]
        output_b = case["baseline_output"] if candidate_label == "A" else candidate_result["output"]
        assessment, grader_metrics = await _grade(
            grader, agent_type, case["input"], output_a, output_b
        )
        candidate_score = assessment.output_a.total if candidate_label == "A" else assessment.output_b.total
        baseline_score = assessment.output_b.total if candidate_label == "A" else assessment.output_a.total
        cheaper = Decimal(candidate_result["cost"]) < Decimal(case["baseline_cost"])
        acceptable = candidate_score >= baseline_score - 3
        record.update(
            {
                "status": "GRADED",
                "candidate_blind_label": candidate_label,
                "baseline_quality": baseline_score,
                "candidate_quality": candidate_score,
                "quality_delta": candidate_score - baseline_score,
                "assessment": assessment.model_dump(mode="json"),
                "grader": grader_metrics,
                "recommendation": (
                    "CANDIDATE_FOR_PROFILE_TRIAL"
                    if cheaper and acceptable
                    else "KEEP_BASELINE"
                ),
            }
        )
        results.append(record)
    return {
        "experiment": "agent-model-quality-cost-ab-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "project_id": args.project_id,
        "candidate_model": args.candidate_model,
        "decision_rule": "candidate cost lower and blind quality no more than 3 points below baseline",
        "results": results,
        "limitations": [
            "One historical case per agent is a screening test, not a final migration decision.",
            "An LLM grader should be complemented by human review before production changes.",
            "Evaluation calls are reported separately and do not alter project history or budget.",
        ],
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    report = asyncio.run(evaluate(args))
    args.output_directory.mkdir(parents=True, exist_ok=True)
    target = args.output_directory / f"agent-model-ab-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
