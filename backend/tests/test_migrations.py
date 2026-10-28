from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import get_settings


def test_migrations_create_current_schema(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "migration.db"
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    sync_url = f"sqlite:///{database_path.as_posix()}"
    backend_dir = Path(__file__).parents[1]

    monkeypatch.setenv("DATABASE_URL", async_url)
    get_settings.cache_clear()

    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "head")

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            "agent_runs",
            "agent_profiles",
            "agent_prompt_versions",
            "alembic_version",
            "criticisms",
            "decisions",
            "development_blueprints",
            "improvement_plans",
            "judge_chat_turns",
            "evidence",
            "experiments",
            "hypotheses",
            "idea_versions",
            "projects",
            "provider_cost_entries",
            "billing_syncs",
            "rounds",
            "scores",
            "workflow_executions",
            "founder_profiles",
            "discovery_campaigns",
            "opportunity_signals",
            "opportunity_candidates",
            "discovery_agent_runs",
            "discovery_prompt_versions",
            "discovery_handoffs",
        }
        assert {column["name"] for column in inspector.get_columns("projects")} == {
            "id",
            "name",
            "raw_idea",
            "agent_profile_id",
            "agent_plan",
            "status",
            "total_cost",
            "max_ai_budget",
            "next_round_context",
            "stagnation_detected",
            "created_at",
            "updated_at",
        }
        assert {column["name"] for column in inspector.get_columns("idea_versions")} == {
            "id",
            "project_id",
            "version",
            "parent_version_id",
            "reason_for_change",
            "created_by",
            "changes",
            "concept",
            "created_at",
        }
        assert {column["name"] for column in inspector.get_columns("criticisms")} == {
            "id",
            "project_id",
            "idea_version_id",
            "agent_run_id",
            "title",
            "severity",
            "claim",
            "reason",
            "affected_hypotheses",
            "evidence_needed",
            "condition_that_refutes_criticism",
            "created_at",
        }
        assert {column["name"] for column in inspector.get_columns("agent_runs")} == {
            "id",
            "project_id",
            "round_id",
            "agent",
            "provider",
            "model",
            "prompt_version",
            "input_json",
            "output_json",
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "web_search_calls",
            "tool_cost",
            "web_sources",
            "estimated_cost",
            "execution_time",
            "error",
            "created_at",
        }
        assert {column["name"] for column in inspector.get_columns("scores")} == {
            "id",
            "project_id",
            "idea_version_id",
            "agent_run_id",
            "total_score",
            "confidence",
            "breakdown",
            "created_at",
        }
        assert {column["name"] for column in inspector.get_columns("decisions")} == {
            "id",
            "project_id",
            "round_number",
            "decision",
            "reason",
            "from_version_id",
            "to_version_id",
            "score_id",
            "agent_run_id",
            "critical_blockers",
            "most_important_unknowns",
            "next_actions",
            "human_review_status",
            "human_action",
            "human_note",
            "reviewed_at",
            "created_at",
        }
        assert {column["name"] for column in inspector.get_columns("rounds")} == {
            "id",
            "project_id",
            "round_number",
            "status",
            "starting_version_id",
            "resulting_version_id",
            "decision",
            "score",
            "confidence",
            "budget_limit_reached",
            "stagnation_detected",
            "error",
            "human_context",
            "started_at",
            "completed_at",
        }
        assert {column["name"] for column in inspector.get_columns("hypotheses")} == {
            "id",
            "project_id",
            "sequence",
            "statement",
            "category",
            "impact",
            "confidence",
            "status",
            "epistemic_classification",
            "origin",
            "source_version_id",
            "created_at",
            "updated_at",
        }
        assert {column["name"] for column in inspector.get_columns("evidence")} == {
            "id",
            "project_id",
            "sequence",
            "hypothesis_id",
            "agent_run_id",
            "source",
            "source_type",
            "claim",
            "direction",
            "strength",
            "epistemic_classification",
            "url",
            "date",
            "origin",
            "created_at",
        }
        assert {column["name"] for column in inspector.get_columns("experiments")} == {
            "id",
            "project_id",
            "decision_id",
            "hypothesis_id",
            "experiment_type",
            "description",
            "success_metric",
            "success_threshold",
            "estimated_cost",
            "actual_cost",
            "status",
            "outcome",
            "result_summary",
            "observed_value",
            "sample_size",
            "methodology",
            "limitations",
            "evidence_id",
            "evidence_quality",
            "affected_criteria",
            "reassessment_status",
            "previous_score",
            "previous_confidence",
            "reassessed_score",
            "reassessed_confidence",
            "reassessment_score_id",
            "reassessment_decision_id",
            "reassessment_error",
            "created_at",
            "updated_at",
            "completed_at",
        }
        assert {column["name"] for column in inspector.get_columns("agent_profiles")} == {
            "id",
            "name",
            "description",
            "agents",
            "created_at",
            "updated_at",
        }
        assert {
            column["name"]
            for column in inspector.get_columns("agent_prompt_versions")
        } == {
            "id",
            "agent",
            "version",
            "content",
            "is_active",
            "created_at",
        }
        assert {
            column["name"]
            for column in inspector.get_columns("provider_cost_entries")
        } == {
            "id",
            "external_reference",
            "provider",
            "source",
            "period_start",
            "period_end",
            "amount",
            "currency",
            "model",
            "line_item",
            "external_project_id",
            "external_api_key_id",
            "quantity",
            "quantity_unit",
            "details",
            "created_at",
            "updated_at",
        }
        assert {
            column["name"] for column in inspector.get_columns("billing_syncs")
        } == {
            "id",
            "provider",
            "status",
            "period_start",
            "period_end",
            "entries_seen",
            "entries_written",
            "error",
            "started_at",
            "completed_at",
        }
        assert {
            column["name"]
            for column in inspector.get_columns("development_blueprints")
        } == {
            "id",
            "project_id",
            "version",
            "status",
            "architecture_alternatives",
            "user_context",
            "max_ai_budget",
            "estimated_cost",
            "product_definition",
            "architecture_options",
            "technical_review",
            "final_blueprint",
            "agent_run_ids",
            "error",
            "created_at",
            "completed_at",
        }
        assert {
            column["name"] for column in inspector.get_columns("improvement_plans")
        } == {
            "id",
            "project_id",
            "round_id",
            "idea_version_id",
            "score_id",
            "decision_id",
            "agent_run_id",
            "version",
            "source_score",
            "source_confidence",
            "plan",
            "created_at",
        }
        assert {
            column["name"] for column in inspector.get_columns("judge_chat_turns")
        } == {
            "id",
            "project_id",
            "decision_id",
            "user_message",
            "input_mode",
            "status",
            "requested_rounds",
            "judge_response",
            "stop_reason",
            "error",
            "cost_before",
            "cost_after",
            "created_at",
            "completed_at",
        }
        agent_run_foreign_keys = inspector.get_foreign_keys("agent_runs")
        assert any(
            key["constrained_columns"] == ["round_id"]
            and key["referred_table"] == "rounds"
            for key in agent_run_foreign_keys
        )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_latest_migration_is_reversible_on_sqlite(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "reversible.db"
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    sync_url = f"sqlite:///{database_path.as_posix()}"
    backend_dir = Path(__file__).parents[1]
    monkeypatch.setenv("DATABASE_URL", async_url)
    get_settings.cache_clear()
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    command.upgrade(config, "head")
    command.downgrade(config, "0013")
    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        assert "provider_cost_entries" in inspector.get_table_names()
        assert "billing_syncs" in inspector.get_table_names()
        assert "provider" in {
            column["name"] for column in inspector.get_columns("agent_runs")
        }
        agent_run_columns = {
            column["name"] for column in inspector.get_columns("agent_runs")
        }
        assert "web_search_calls" not in agent_run_columns
        assert "tool_cost" not in agent_run_columns
        assert "web_sources" not in agent_run_columns
        assert "agent_prompt_versions" in inspector.get_table_names()
        assert "experiments" in inspector.get_table_names()
        assert "agent_profiles" in inspector.get_table_names()
        assert "development_blueprints" not in inspector.get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    get_settings.cache_clear()
