import pytest
from httpx import AsyncClient

from app.llm.dependencies import get_llm_router
from app.llm.providers.mock import MockLLMProvider
from app.llm.router import LLMRouter
from app.main import app


pytestmark = pytest.mark.anyio


def profile_payload(name: str = "Balanced mock") -> dict[str, object]:
    agents = {
        agent: {
            "provider": "mock",
            "model": f"profile-{agent.lower()}",
            "input_cost_per_million": "0",
            "output_cost_per_million": "0",
        }
        for agent in ("STRUCTURER", "BUILDER", "RESEARCHER", "CRITIC", "JUDGE")
    }
    return {"name": name, "description": "Reusable offline profile", "agents": agents}


async def test_profile_drives_project_models_and_can_be_reassigned(
    client: AsyncClient,
) -> None:
    created_profile = await client.post("/agent-profiles", json=profile_payload())
    assert created_profile.status_code == 201
    profile_id = created_profile.json()["id"]
    project = await client.post(
        "/projects",
        json={
            "name": "Profile project",
            "raw_idea": "Test profile routing",
            "agent_profile_id": profile_id,
        },
    )
    assert project.status_code == 201
    assert project.json()["agent_profile_id"] == profile_id

    updated_payload = profile_payload("Balanced mock updated")
    updated_payload["description"] = "Updated safely from the profile editor"
    updated_profile = await client.put(
        f"/agent-profiles/{profile_id}", json=updated_payload
    )
    assert updated_profile.status_code == 200
    assert updated_profile.json()["name"] == "Balanced mock updated"
    assert updated_profile.json()["description"] == updated_payload["description"]

    run = await client.post(
        f"/projects/{project.json()['id']}/run", json={"max_rounds": 1}
    )
    timeline = await client.get(f"/projects/{project.json()['id']}/timeline")
    assert run.status_code == 200
    assert {item["model"] for item in timeline.json()} == {
        "profile-structurer",
        "profile-builder",
        "profile-researcher",
        "profile-critic",
        "profile-judge",
    }

    detached = await client.patch(
        f"/projects/{project.json()['id']}/agent-profile",
        json={"agent_profile_id": None},
    )
    reattached = await client.patch(
        f"/projects/{project.json()['id']}/agent-profile",
        json={"agent_profile_id": profile_id},
    )
    deleted = await client.delete(f"/agent-profiles/{profile_id}")
    project_after_delete = await client.get(f"/projects/{project.json()['id']}")
    assert detached.status_code == 200
    assert detached.json()["agent_profile_id"] is None
    assert reattached.status_code == 200
    assert reattached.json()["agent_profile_id"] == profile_id
    assert deleted.status_code == 204
    assert project_after_delete.json()["agent_profile_id"] is None

    invalid_payload = profile_payload("Invalid")
    invalid_payload["agents"]["CRITIC"]["provider"] = "not-installed"
    invalid = await client.post("/agent-profiles", json=invalid_payload)
    assert invalid.status_code == 422
    assert "not-installed" in invalid.json()["detail"]


async def test_experiment_blocks_runs_until_a_typed_result_is_completed(
    client: AsyncClient,
) -> None:
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    project = await client.post(
        "/projects", json={"name": "Experiment", "raw_idea": "Test an assumption"}
    )
    project_id = project.json()["id"]
    structured = await client.post(f"/projects/{project_id}/structure")
    assert structured.status_code == 201
    experiment = await client.post(
        f"/projects/{project_id}/experiments",
        json={
            "experiment_type": "INTERVIEW",
            "description": "Interview five target users",
            "success_metric": "Paid pilot commitments",
            "success_threshold": "At least two commitments",
            "estimated_cost": "50",
        },
    )
    assert experiment.status_code == 201
    blocked = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    assert blocked.status_code == 409

    invalid_completion = await client.patch(
        f"/projects/{project_id}/experiments/{experiment.json()['id']}",
        json={"status": "COMPLETED"},
    )
    assert invalid_completion.status_code == 422
    completed = await client.patch(
        f"/projects/{project_id}/experiments/{experiment.json()['id']}",
        json={
            "status": "COMPLETED",
            "outcome": "SUCCESS",
            "result_summary": "Three target users signed paid pilot letters.",
            "observed_value": "3 signed pilot letters",
            "sample_size": 5,
            "methodology": "Five structured interviews using the same script and pricing offer.",
            "limitations": "Small convenience sample from one customer segment.",
            "actual_cost": "42.50",
        },
    )
    assert completed.status_code == 200
    assert completed.json()["completed_at"] is not None
    assert completed.json()["evidence_quality"] == 5
    assert completed.json()["evidence_id"] is not None
    assert completed.json()["reassessment_status"] == "PENDING"
    assert "MARKET" in completed.json()["affected_criteria"]

    reassessed = await client.post(
        f"/projects/{project_id}/experiments/{experiment.json()['id']}/reassess"
    )
    assert reassessed.status_code == 200
    assert reassessed.json()["reassessment_status"] == "COMPLETED"
    assert reassessed.json()["reassessed_score"] == 60

    evidence = await client.get(f"/projects/{project_id}/evidence")
    hypotheses = await client.get(f"/projects/{project_id}/hypotheses")
    assert evidence.json()[-1]["origin"] == "EXPERIMENT"
    assert evidence.json()[-1]["strength"] == 5
    assert hypotheses.json()[-1]["status"] == "VALIDATED"
    confidence_after_completion = hypotheses.json()[-1]["confidence"]

    repeated = await client.post(
        f"/projects/{project_id}/experiments/{experiment.json()['id']}/reassess"
    )
    repeated_evidence = await client.get(f"/projects/{project_id}/evidence")
    repeated_hypotheses = await client.get(f"/projects/{project_id}/hypotheses")
    assert repeated.status_code == 200
    assert repeated.json()["reassessment_status"] == "COMPLETED"
    assert len(repeated_evidence.json()) == len(evidence.json())
    assert repeated_hypotheses.json()[-1]["confidence"] == confidence_after_completion

    run = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    assert run.status_code == 200
    judge_call = [call for call in provider.calls if call.role == "JUDGE"][0]
    assert judge_call.input_data["experiments"][0]["outcome"] == "SUCCESS"


async def test_experiment_evidence_survives_when_reassessment_has_no_budget(
    client: AsyncClient,
) -> None:
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    project = await client.post(
        "/projects", json={"name": "Budgeted experiment", "raw_idea": "Test safely"}
    )
    project_id = project.json()["id"]
    assert (await client.post(f"/projects/{project_id}/structure")).status_code == 201
    assert (
        await client.patch(
            f"/projects/{project_id}/budget", json={"max_ai_budget": "0"}
        )
    ).status_code == 200
    experiment = await client.post(
        f"/projects/{project_id}/experiments",
        json={
            "experiment_type": "LOAD_TEST",
            "description": "Measure API throughput under representative load",
            "success_metric": "Requests per second",
            "success_threshold": "At least 100 requests per second",
        },
    )
    completed = await client.patch(
        f"/projects/{project_id}/experiments/{experiment.json()['id']}",
        json={
            "status": "COMPLETED",
            "outcome": "INCONCLUSIVE",
            "result_summary": "The load generator failed before reaching the target.",
        },
    )
    assert completed.status_code == 200
    assert completed.json()["evidence_id"] is not None
    assert completed.json()["reassessment_status"] == "PENDING"

    reassessed = await client.post(
        f"/projects/{project_id}/experiments/{experiment.json()['id']}/reassess"
    )
    assert reassessed.status_code == 200
    assert reassessed.json()["reassessment_status"] == "SKIPPED_BUDGET"
    assert reassessed.json()["reassessment_error"]


async def test_health_metrics_reports_backup_and_restore(client: AsyncClient) -> None:
    provider = MockLLMProvider()
    app.dependency_overrides[get_llm_router] = lambda: LLMRouter.from_single_provider(
        provider
    )
    health = await client.get("/health")
    ready = await client.get("/ready")
    config = await client.get("/system/config")
    assert health.status_code == ready.status_code == config.status_code == 200
    assert health.json()["version"] == "1.0.0"
    assert all("api_key" not in item for item in config.json()["providers"])
    assert all(
        "input_cost_per_million" in item
        and "output_cost_per_million" in item
        for item in config.json()["providers"]
    )

    project = await client.post(
        "/projects", json={"name": "Portable", "raw_idea": "Export this project"}
    )
    project_id = project.json()["id"]
    run = await client.post(
        f"/projects/{project_id}/run", json={"max_rounds": 1}
    )
    assert run.status_code == 200

    project_metrics = await client.get(f"/projects/{project_id}/metrics")
    efficiency = await client.get(f"/projects/{project_id}/efficiency")
    report = await client.get(f"/projects/{project_id}/report")
    markdown = await client.get(f"/projects/{project_id}/report.md")
    focused = await client.patch(
        f"/projects/{project_id}/agent-plan",
        json={"agent_plan": {"builder": 0, "researcher": 3, "critic": 2}},
    )
    backup = await client.get(f"/projects/{project_id}/backup")
    restored = await client.post("/projects/import", json=backup.json())

    assert project_metrics.status_code == 200
    assert project_metrics.json()["total_runs"] == 8
    assert len(project_metrics.json()["by_agent"]) == 6
    assert efficiency.status_code == 200
    assert len(efficiency.json()["rounds"]) == 1
    assert efficiency.json()["rounds"][0]["calls"] == 7
    assert efficiency.json()["recommendation"] == "CRIAR_REFERENCIA"
    assert report.status_code == 200
    assert report.json()["project"]["name"] == "Portable"
    assert markdown.status_code == 200
    assert markdown.text.startswith("# Portable")
    assert focused.status_code == 200
    assert "attachment" in markdown.headers["content-disposition"]
    assert backup.status_code == 200
    assert backup.json()["schema_version"] == "1.4"
    assert restored.status_code == 201
    assert restored.json()["id"] != project_id
    assert restored.json()["name"] == "Portable (restored)"
    assert backup.json()["data"]["projects"][0]["agent_plan"] == {
        "builder": 0,
        "researcher": 3,
        "critic": 2,
    }
    assert restored.json()["agent_plan"] == {
        "builder": 0,
        "researcher": 3,
        "critic": 2,
    }
