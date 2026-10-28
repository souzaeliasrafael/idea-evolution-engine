from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
import random
import sqlite3
from statistics import mean
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.base import AgentExecutionError, AgentResult
from app.agents.critic import CriticAgent
from app.core.config import get_settings
from app.domain.enums import AgentType
from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.llm.dependencies import get_provider_registry
from app.llm.prompts import load_prompt
from app.llm.router import config_for_agent
from app.schemas.evaluation import CriticOutput


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "iee.db"
DEFAULT_CANDIDATE_PROMPT = (
    BACKEND_ROOT / "evals" / "prompts" / "critic_financial_systems_v1.md"
)
DEFAULT_OUTPUT_DIRECTORY = BACKEND_ROOT / "work" / "specialization-experiments"


class RubricScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_risk_coverage: Annotated[int, Field(ge=0, le=20)]
    domain_specificity: Annotated[int, Field(ge=0, le=20)]
    factual_discipline: Annotated[int, Field(ge=0, le=20)]
    falsifiability_and_evidence: Annotated[int, Field(ge=0, le=20)]
    prioritization_and_actionability: Annotated[int, Field(ge=0, le=20)]

    @property
    def total(self) -> int:
        return (
            self.material_risk_coverage
            + self.domain_specificity
            + self.factual_discipline
            + self.falsifiability_and_evidence
            + self.prioritization_and_actionability
        )


class PairwiseAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_a: RubricScore
    output_b: RubricScore
    preferred_output: Literal["A", "B", "TIE"]
    decisive_reasons: Annotated[list[str], Field(min_length=1, max_length=3)]
    evaluation_limitations: Annotated[list[str], Field(max_length=3)]


@dataclass(frozen=True)
class ExperimentCase:
    run_id: str
    created_at: str
    input_data: dict[str, Any]


PAIRWISE_PROMPT = """# Blind Critic Evaluation

Compare two Critic outputs produced from exactly the same project context. Do
not infer which prompt produced either output and do not reward verbosity.

Score each output independently from 0 to 20 on each criterion:

1. material_risk_coverage: identifies the risks most capable of invalidating
   the product, financial result, safety, or legal operation;
2. domain_specificity: applies relevant technical and financial-system concepts
   rather than generic startup criticism;
3. factual_discipline: distinguishes supplied evidence from assumptions and
   does not invent facts;
4. falsifiability_and_evidence: makes criticisms testable and requests evidence
   capable of confirming or refuting them;
5. prioritization_and_actionability: prioritizes decisive issues and explains
   what must be investigated next without redesigning the product.

Use only the supplied project context and outputs. A criticism is not better
merely because it is harsher. Prefer the output with the higher rubric quality;
return TIE only when the totals and practical usefulness are effectively equal.
Return strict JSON matching the supplied schema.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a blind, non-mutating A/B evaluation of the current Critic "
            "prompt against a specialist candidate prompt."
        )
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--cases", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--candidate-prompt", type=Path, default=DEFAULT_CANDIDATE_PROMPT
    )
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--seed", type=int, default=20260919)
    return parser.parse_args()


def load_cases(database: Path, project_id: str, limit: int) -> list[ExperimentCase]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, input_json
            FROM agent_runs
            WHERE project_id = ?
              AND agent = 'CRITIC'
              AND error IS NULL
              AND input_json IS NOT NULL
            ORDER BY created_at DESC, id DESC
            """,
            (project_id,),
        ).fetchall()

    cases: list[ExperimentCase] = []
    seen_inputs: set[str] = set()
    for run_id, created_at, encoded_input in rows:
        input_data = json.loads(encoded_input)
        fingerprint = json.dumps(input_data, ensure_ascii=False, sort_keys=True)
        if fingerprint in seen_inputs:
            continue
        seen_inputs.add(fingerprint)
        cases.append(
            ExperimentCase(
                run_id=str(run_id),
                created_at=str(created_at),
                input_data=input_data,
            )
        )
        if len(cases) == limit:
            break

    if len(cases) < limit:
        raise RuntimeError(
            f"Only {len(cases)} distinct successful Critic cases are available; "
            f"{limit} were requested."
        )
    return cases


def load_baseline_prompt(database: Path) -> tuple[str, str]:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            """
            SELECT content, version
            FROM agent_prompt_versions
            WHERE agent = 'CRITIC' AND is_active = 1
            ORDER BY version DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    if row is not None:
        return str(row[0]), f"custom-v{row[1]}"
    return load_prompt("critic", "v1"), "v1"


def response_metrics(result: AgentResult[CriticOutput]) -> dict[str, Any]:
    responses = [attempt.response for attempt in result.attempts if attempt.response]
    return {
        "attempts": len(result.attempts),
        "input_tokens": sum(response.input_tokens for response in responses),
        "output_tokens": sum(response.output_tokens for response in responses),
        "estimated_cost": str(
            sum((response.estimated_cost for response in responses), Decimal("0"))
        ),
        "execution_time_seconds": round(
            sum(attempt.execution_time for attempt in result.attempts), 3
        ),
        "model": responses[-1].model if responses else None,
    }


def failed_metrics(error: AgentExecutionError) -> dict[str, Any]:
    responses = [attempt.response for attempt in error.attempts if attempt.response]
    return {
        "attempts": len(error.attempts),
        "input_tokens": sum(response.input_tokens for response in responses),
        "output_tokens": sum(response.output_tokens for response in responses),
        "estimated_cost": str(
            sum((response.estimated_cost for response in responses), Decimal("0"))
        ),
        "execution_time_seconds": round(
            sum(attempt.execution_time for attempt in error.attempts), 3
        ),
        "model": responses[-1].model if responses else None,
    }


async def run_arm(
    provider: LLMProvider,
    *,
    prompt: str,
    prompt_version: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    agent = CriticAgent(
        provider,
        max_attempts=2,
        prompt=prompt,
        prompt_version=prompt_version,
    )
    try:
        result = await agent.execute(input_data)
    except AgentExecutionError as exc:
        return {
            "succeeded": False,
            "output": None,
            "last_error": exc.attempts[-1].error if exc.attempts else "unknown error",
            "metrics": failed_metrics(exc),
        }
    return {
        "succeeded": True,
        "output": result.output.model_dump(mode="json"),
        "last_error": None,
        "metrics": response_metrics(result),
    }


async def grade_pair(
    provider: LLMProvider,
    *,
    project_context: dict[str, Any],
    output_a: dict[str, Any],
    output_b: dict[str, Any],
) -> tuple[PairwiseAssessment, LLMResponse]:
    request = LLMRequest(
        role="SPECIALIZATION_EVALUATOR",
        prompt=PAIRWISE_PROMPT,
        input_data={
            "project_context": project_context,
            "output_a": output_a,
            "output_b": output_b,
        },
        output_schema_name="critic_pairwise_assessment",
        output_schema=PairwiseAssessment.model_json_schema(),
        max_output_tokens=2048,
    )
    last_error: Exception | None = None
    for _ in range(2):
        response = await provider.generate(request)
        try:
            return PairwiseAssessment.model_validate_json(response.content), response
        except Exception as exc:  # pragma: no cover - exercised only by live providers
            last_error = exc
    raise RuntimeError(f"Pairwise evaluator returned invalid output: {last_error}")


def cost_of(record: dict[str, Any]) -> Decimal:
    return Decimal(record["metrics"]["estimated_cost"])


async def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    registry = get_provider_registry()
    critic_provider = registry.create(config_for_agent(settings, AgentType.CRITIC))
    judge_provider = registry.create(config_for_agent(settings, AgentType.JUDGE))
    cases = load_cases(args.database.resolve(), args.project_id, args.cases)
    baseline_prompt, baseline_version = load_baseline_prompt(args.database.resolve())
    candidate_prompt = args.candidate_prompt.resolve().read_text(encoding="utf-8")
    rng = random.Random(args.seed)
    case_results: list[dict[str, Any]] = []

    for index, case in enumerate(cases, start=1):
        baseline, candidate = await asyncio.gather(
            run_arm(
                critic_provider,
                prompt=baseline_prompt,
                prompt_version=baseline_version,
                input_data=case.input_data,
            ),
            run_arm(
                critic_provider,
                prompt=candidate_prompt,
                prompt_version="financial-specialist-experiment-v1",
                input_data=case.input_data,
            ),
        )
        if not baseline["succeeded"] or not candidate["succeeded"]:
            case_results.append(
                {
                    "case": index,
                    "source_run_id": case.run_id,
                    "source_created_at": case.created_at,
                    "baseline": baseline,
                    "candidate": candidate,
                    "assessment": None,
                    "grader": None,
                }
            )
            continue

        candidate_label = "A" if rng.choice((True, False)) else "B"
        output_a = candidate["output"] if candidate_label == "A" else baseline["output"]
        output_b = baseline["output"] if candidate_label == "A" else candidate["output"]
        assessment, grader_response = await grade_pair(
            judge_provider,
            project_context=case.input_data,
            output_a=output_a,
            output_b=output_b,
        )
        candidate_score = (
            assessment.output_a.total
            if candidate_label == "A"
            else assessment.output_b.total
        )
        baseline_score = (
            assessment.output_b.total
            if candidate_label == "A"
            else assessment.output_a.total
        )
        case_results.append(
            {
                "case": index,
                "source_run_id": case.run_id,
                "source_created_at": case.created_at,
                "candidate_blind_label": candidate_label,
                "baseline": baseline,
                "candidate": candidate,
                "assessment": assessment.model_dump(mode="json"),
                "normalized_scores": {
                    "baseline": baseline_score,
                    "candidate": candidate_score,
                    "delta": candidate_score - baseline_score,
                },
                "grader": {
                    "model": grader_response.model,
                    "input_tokens": grader_response.input_tokens,
                    "output_tokens": grader_response.output_tokens,
                    "estimated_cost": str(grader_response.estimated_cost),
                },
            }
        )

    graded = [item for item in case_results if item["assessment"] is not None]
    baseline_scores = [item["normalized_scores"]["baseline"] for item in graded]
    candidate_scores = [item["normalized_scores"]["candidate"] for item in graded]
    baseline_cost = sum((cost_of(item["baseline"]) for item in case_results), Decimal("0"))
    candidate_cost = sum((cost_of(item["candidate"]) for item in case_results), Decimal("0"))
    grader_cost = sum(
        (Decimal(item["grader"]["estimated_cost"]) for item in graded), Decimal("0")
    )
    summary = {
        "cases_requested": args.cases,
        "cases_graded": len(graded),
        "baseline_schema_successes": sum(item["baseline"]["succeeded"] for item in case_results),
        "candidate_schema_successes": sum(item["candidate"]["succeeded"] for item in case_results),
        "baseline_average_score": round(mean(baseline_scores), 2) if graded else None,
        "candidate_average_score": round(mean(candidate_scores), 2) if graded else None,
        "average_score_delta": (
            round(mean(candidate_scores) - mean(baseline_scores), 2) if graded else None
        ),
        "candidate_wins": sum(
            item["normalized_scores"]["candidate"]
            > item["normalized_scores"]["baseline"]
            for item in graded
        ),
        "baseline_wins": sum(
            item["normalized_scores"]["baseline"]
            > item["normalized_scores"]["candidate"]
            for item in graded
        ),
        "ties": sum(
            item["normalized_scores"]["baseline"]
            == item["normalized_scores"]["candidate"]
            for item in graded
        ),
        "baseline_generation_cost": str(baseline_cost),
        "candidate_generation_cost": str(candidate_cost),
        "grader_cost": str(grader_cost),
        "total_experiment_cost": str(baseline_cost + candidate_cost + grader_cost),
    }
    return {
        "experiment": "critic-prompt-specialization-ab",
        "created_at": datetime.now(UTC).isoformat(),
        "project_id": args.project_id,
        "baseline_prompt_version": baseline_version,
        "candidate_prompt": str(args.candidate_prompt.resolve()),
        "seed": args.seed,
        "method": {
            "description": (
                "Blind A/B comparison on historical production contexts. The project "
                "database is read-only and generated criticisms are not persisted."
            ),
            "rubric_points": 100,
            "limitations": [
                "This evaluates prompt specialization, not weight fine-tuning.",
                "An LLM grader is a useful pilot signal but does not replace expert review.",
                "Historical contexts from one project do not establish generalization.",
            ],
        },
        "summary": summary,
        "cases": case_results,
    }


def main() -> None:
    args = parse_args()
    report = asyncio.run(run_experiment(args))
    args.output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = args.output_directory / f"critic-specialization-{timestamp}.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"REPORT={output_path.resolve()}")


if __name__ == "__main__":
    main()
