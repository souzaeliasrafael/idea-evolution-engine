"""Project cheaper-model savings from recorded per-agent token usage.

This is a cost screen, not a quality claim. It deliberately leaves production
profiles unchanged until an agent-specific quality eval is run.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path

from sqlalchemy import select

from app.database.models import AgentRun, Project
from app.database.session import AsyncSessionMaker
from app.llm.providers.http import TokenPricing


async def evaluate(args: argparse.Namespace) -> dict[str, object]:
    candidate = TokenPricing(
        input_per_million=Decimal(args.candidate_input_rate),
        cached_input_per_million=Decimal(args.candidate_cached_input_rate),
        output_per_million=Decimal(args.candidate_output_rate),
    )
    async with AsyncSessionMaker() as session:
        project = await session.get(Project, args.project_id)
        if project is None:
            raise SystemExit(f"Project not found: {args.project_id}")
        runs = list(
            (
                await session.scalars(
                    select(AgentRun).where(AgentRun.project_id == project.id)
                )
            ).all()
        )

    groups: dict[str, list[AgentRun]] = defaultdict(list)
    for run in runs:
        groups[run.agent.value].append(run)

    by_agent: list[dict[str, object]] = []
    total_current = Decimal("0")
    total_candidate = Decimal("0")
    for agent, agent_runs in sorted(groups.items()):
        current = sum(
            (Decimal(run.estimated_cost) for run in agent_runs), Decimal("0")
        )
        projected = sum(
            (
                candidate.estimate(
                    run.input_tokens,
                    run.output_tokens,
                    run.cached_input_tokens,
                )
                + Decimal(run.tool_cost)
                for run in agent_runs
            ),
            Decimal("0"),
        )
        total_current += current
        total_candidate += projected
        savings = current - projected
        recommendation = (
            "candidate_trial"
            if agent in {"STRUCTURER", "RESEARCHER", "CRITIC", "IMPROVER"}
            else "keep_current_until_quality_eval"
        )
        by_agent.append(
            {
                "agent": agent,
                "calls": len(agent_runs),
                "input_tokens": sum(run.input_tokens for run in agent_runs),
                "cached_input_tokens": sum(
                    run.cached_input_tokens for run in agent_runs
                ),
                "output_tokens": sum(run.output_tokens for run in agent_runs),
                "current_cost_usd": _money(current),
                "candidate_cost_usd": _money(projected),
                "projected_savings_usd": _money(savings),
                "projected_savings_percent": _percent(savings, current),
                "recommendation": recommendation,
            }
        )

    return {
        "analysis": "agent-model-cost-screen-v1",
        "project_id": project.id,
        "project_name": project.name,
        "candidate_model": args.candidate_model,
        "pricing_usd_per_million": {
            "input": args.candidate_input_rate,
            "cached_input": args.candidate_cached_input_rate,
            "output": args.candidate_output_rate,
        },
        "total_current_cost_usd": _money(total_current),
        "total_candidate_cost_usd": _money(total_candidate),
        "total_projected_savings_usd": _money(total_current - total_candidate),
        "total_projected_savings_percent": _percent(
            total_current - total_candidate, total_current
        ),
        "by_agent": by_agent,
        "decision": (
            "Do not switch Builder or Judge on cost alone. Trial the candidate "
            "first on lower-risk agents and require schema-validity and quality "
            "evals before changing a production profile."
        ),
        "limitations": [
            "Projection assumes the candidate uses the same number of tokens.",
            "Web-search tool charges are retained unchanged.",
            "This report measures cost only; it does not establish output quality.",
        ],
    }


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001")))


def _percent(value: Decimal, base: Decimal) -> float:
    if base <= 0:
        return 0.0
    return round(float(value / base * 100), 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--candidate-model", default="gpt-5.6-luna")
    parser.add_argument("--candidate-input-rate", default="0.20")
    parser.add_argument("--candidate-cached-input-rate", default="0.02")
    parser.add_argument("--candidate-output-rate", default="1.20")
    parser.add_argument("--output")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    report = asyncio.run(evaluate(arguments))
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if arguments.output:
        target = Path(arguments.output).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
