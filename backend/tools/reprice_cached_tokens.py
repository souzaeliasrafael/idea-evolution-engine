"""Recalculate recorded model costs with a distinct cached-input rate.

Dry-run by default. Pass --apply only after reviewing the JSON summary.
"""

from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import json

from sqlalchemy import func, select

from app.database.models import AgentRun, Project
from app.database.session import AsyncSessionMaker
from app.llm.providers.http import TokenPricing


async def reprice(args: argparse.Namespace) -> dict[str, object]:
    pricing = TokenPricing(
        input_per_million=Decimal(args.input_rate),
        cached_input_per_million=Decimal(args.cached_input_rate),
        output_per_million=Decimal(args.output_rate),
    )
    async with AsyncSessionMaker() as session:
        if args.all_projects:
            projects = list(
                (await session.scalars(select(Project).order_by(Project.created_at))).all()
            )
        else:
            project = await session.get(Project, args.project_id)
            if project is None:
                raise SystemExit(f"Project not found: {args.project_id}")
            projects = [project]

        results: list[dict[str, object]] = []
        for project in projects:
            results.append(await _reprice_project(session, project, pricing, args))
        if args.apply:
            await session.commit()
        return {
            "applied": bool(args.apply),
            "scope": "all_projects" if args.all_projects else "single_project",
            "provider": args.provider,
            "model": args.model,
            "projects_scanned": len(projects),
            "runs_repriced": sum(int(item["runs_repriced"]) for item in results),
            "total_savings": str(
                sum(
                    (Decimal(str(item["matching_savings"])) for item in results),
                    Decimal("0"),
                ).quantize(Decimal("0.000001"))
            ),
            "projects": results,
        }


async def _reprice_project(
    session: object,
    project: Project,
    pricing: TokenPricing,
    args: argparse.Namespace,
) -> dict[str, object]:
    # Kept as a separate unit so an all-project run is one atomic transaction.
    from sqlalchemy.ext.asyncio import AsyncSession

    assert isinstance(session, AsyncSession)
    runs = list(
        (
            await session.scalars(
                select(AgentRun)
                .where(
                    AgentRun.project_id == project.id,
                    AgentRun.provider == args.provider,
                    AgentRun.model.like(f"{args.model}%"),
                )
                .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
            )
        ).all()
    )
    before = sum((Decimal(run.estimated_cost) for run in runs), Decimal("0"))
    after = Decimal("0")
    for run in runs:
        corrected = pricing.estimate(
            run.input_tokens,
            run.output_tokens,
            run.cached_input_tokens,
        ) + Decimal(run.tool_cost)
        corrected = corrected.quantize(Decimal("0.000001"))
        after += corrected
        if args.apply:
            run.estimated_cost = corrected

    project_before = Decimal(project.total_cost)
    project_after = project_before
    if args.apply:
        await session.flush()
        project_after = Decimal(
            await session.scalar(
                select(func.coalesce(func.sum(AgentRun.estimated_cost), 0)).where(
                    AgentRun.project_id == project.id
                )
            )
        ).quantize(Decimal("0.000001"))
        project.total_cost = project_after

    return {
        "project_id": project.id,
        "project_name": project.name,
        "runs_repriced": len(runs),
        "matching_cost_before": str(before.quantize(Decimal("0.000001"))),
        "matching_cost_after": str(after.quantize(Decimal("0.000001"))),
        "matching_savings": str((before - after).quantize(Decimal("0.000001"))),
        "project_cost_before": str(project_before.quantize(Decimal("0.000001"))),
        "project_cost_after": str(project_after.quantize(Decimal("0.000001"))),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id", nargs="?")
    parser.add_argument("--all-projects", action="store_true")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="gpt-5-mini")
    parser.add_argument("--input-rate", default="0.25")
    parser.add_argument("--cached-input-rate", default="0.025")
    parser.add_argument("--output-rate", default="2.00")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if bool(args.project_id) == bool(args.all_projects):
        parser.error("provide a project_id or --all-projects, but not both")
    return args


if __name__ == "__main__":
    print(json.dumps(asyncio.run(reprice(parse_args())), indent=2, ensure_ascii=False))
