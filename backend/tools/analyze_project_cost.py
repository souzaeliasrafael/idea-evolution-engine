from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sqlite3
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = BACKEND_ROOT / "iee.db"
DEFAULT_OUTPUT_DIRECTORY = BACKEND_ROOT / "work" / "cost-analysis"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a read-only project cost and retry analysis."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--input-price", type=Decimal, default=Decimal("0.25"))
    parser.add_argument("--cached-input-price", type=Decimal, default=Decimal("0.025"))
    parser.add_argument("--output-price", type=Decimal, default=Decimal("2.00"))
    parser.add_argument("--web-search-price", type=Decimal, default=Decimal("0.01"))
    return parser.parse_args()


def _rows(connection: sqlite3.Connection, query: str, values: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, values)]


def _money(value: Decimal | float | int | str) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def run(args: argparse.Namespace) -> Path:
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        project_row = connection.execute(
            """
            SELECT id, name, status, total_cost, max_ai_budget, agent_plan
            FROM projects WHERE id = ?
            """,
            (args.project_id,),
        ).fetchone()
        if project_row is None:
            raise SystemExit(f"Project not found: {args.project_id}")
        project = dict(project_row)
        agents = _rows(
            connection,
            """
            SELECT agent,
                   COUNT(*) AS requests,
                   SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS successes,
                   SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS failures,
                   SUM(input_tokens) AS input_tokens,
                   SUM(cached_input_tokens) AS cached_input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(web_search_calls) AS web_search_calls,
                   ROUND(SUM(estimated_cost), 6) AS app_estimated_cost,
                   ROUND(SUM(CASE WHEN error IS NOT NULL THEN estimated_cost ELSE 0 END), 6)
                     AS failed_request_cost
            FROM agent_runs
            WHERE project_id = ?
            GROUP BY agent
            ORDER BY app_estimated_cost DESC
            """,
            (args.project_id,),
        )
        rounds = _rows(
            connection,
            """
            SELECT r.round_number, r.status, r.score, r.confidence, r.error,
                   r.budget_limit_reached,
                   r.started_at, r.completed_at,
                   COUNT(a.id) AS requests,
                   SUM(CASE WHEN a.error IS NULL THEN 1 ELSE 0 END) AS successes,
                   SUM(CASE WHEN a.error IS NOT NULL THEN 1 ELSE 0 END) AS failures,
                   COALESCE(SUM(a.input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(a.cached_input_tokens), 0) AS cached_input_tokens,
                   COALESCE(SUM(a.output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(a.web_search_calls), 0) AS web_search_calls,
                   ROUND(COALESCE(SUM(a.estimated_cost), 0), 6) AS app_estimated_cost
            FROM rounds r
            LEFT JOIN agent_runs a ON a.round_id = r.id
            WHERE r.project_id = ?
            GROUP BY r.id
            ORDER BY r.round_number
            """,
            (args.project_id,),
        )
        totals = dict(
            connection.execute(
                """
                SELECT COUNT(*) AS requests,
                       SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS successes,
                       SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS failures,
                       SUM(input_tokens) AS input_tokens,
                       SUM(cached_input_tokens) AS cached_input_tokens,
                       SUM(output_tokens) AS output_tokens,
                       SUM(web_search_calls) AS web_search_calls,
                       SUM(estimated_cost) AS app_estimated_cost,
                       SUM(CASE WHEN error IS NOT NULL THEN estimated_cost ELSE 0 END)
                         AS failed_request_cost
                FROM agent_runs WHERE project_id = ?
                """,
                (args.project_id,),
            ).fetchone()
        )

    input_tokens = int(totals["input_tokens"] or 0)
    cached_tokens = int(totals["cached_input_tokens"] or 0)
    output_tokens = int(totals["output_tokens"] or 0)
    web_calls = int(totals["web_search_calls"] or 0)
    uncached_tokens = max(0, input_tokens - cached_tokens)
    cache_adjusted = (
        Decimal(uncached_tokens) * args.input_price
        + Decimal(cached_tokens) * args.cached_input_price
        + Decimal(output_tokens) * args.output_price
    ) / Decimal("1000000") + Decimal(web_calls) * args.web_search_price
    app_estimate = Decimal(str(totals["app_estimated_cost"] or 0))
    failed_cost = Decimal(str(totals["failed_request_cost"] or 0))
    completed_rounds = [row for row in rounds if row["status"] == "COMPLETED"]
    evaluated_rounds = [row for row in completed_rounds if row["score"] is not None]
    evaluated_round_costs = [
        Decimal(str(row["app_estimated_cost"])) for row in evaluated_rounds
    ]
    successful_judge = next((row for row in agents if row["agent"] == "JUDGE"), None)
    judge_mean = (
        Decimal(str(successful_judge["app_estimated_cost"]))
        / Decimal(int(successful_judge["successes"]))
        if successful_judge and successful_judge["successes"]
        else Decimal("0")
    )
    evaluated_mean = (
        sum(evaluated_round_costs, Decimal("0")) / Decimal(len(evaluated_round_costs))
        if evaluated_round_costs
        else Decimal("0")
    )

    report = {
        "analysis": "project-cost-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "project": project,
        "pricing_assumption_usd_per_million": {
            "input": str(args.input_price),
            "cached_input": str(args.cached_input_price),
            "output": str(args.output_price),
            "web_search_per_call": str(args.web_search_price),
        },
        "totals": {
            **totals,
            "uncached_input_tokens": uncached_tokens,
            "app_estimated_cost_usd": _money(app_estimate),
            "cache_adjusted_estimate_usd": _money(cache_adjusted),
            "app_overstatement_from_ignoring_cached_discount_usd": _money(
                app_estimate - cache_adjusted
            ),
            "failed_request_cost_usd": _money(failed_cost),
            "failed_request_share_percent": (
                round(float(failed_cost / app_estimate * 100), 1) if app_estimate else 0
            ),
        },
        "comparison": {
            "completed_rounds": len(completed_rounds),
            "evaluated_rounds_with_score": len(evaluated_rounds),
            "budget_stopped_rounds": sum(
                1 for row in rounds if row["budget_limit_reached"]
            ),
            "mean_app_estimated_cost_per_evaluated_round_usd": _money(evaluated_mean),
            "mean_app_estimated_cost_per_successful_judge_call_usd": _money(judge_mean),
            "evaluated_round_to_single_judge_cost_multiplier": (
                round(float(evaluated_mean / judge_mean), 1) if judge_mean else None
            ),
        },
        "by_agent": agents,
        "by_round": rounds,
        "limitations": [
            "Application estimates are not an OpenAI invoice or organization cost export.",
            "The cache-adjusted estimate applies the supplied prices to recorded token counts.",
            "A single Judge call is a cost baseline, not a quality-equivalent replacement for the workflow.",
        ],
    }
    args.output_directory.mkdir(parents=True, exist_ok=True)
    path = args.output_directory / (
        f"project-cost-{args.project_id[:8]}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    print(json.dumps(report["comparison"], ensure_ascii=False, indent=2))
    print(f"Report: {path}")
    return path


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
