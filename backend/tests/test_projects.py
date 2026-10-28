from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.anyio


async def test_create_project(client: AsyncClient) -> None:
    response = await client.post(
        "/projects",
        json={
            "name": "Evidence-first discovery",
            "raw_idea": "Evaluate product ideas before building them.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert body["name"] == "Evidence-first discovery"
    assert body["raw_idea"] == "Evaluate product ideas before building them."
    assert body["agent_plan"] == {"builder": 1, "researcher": 1, "critic": 1}
    assert body["status"] == "DRAFT"
    assert body["total_cost"] == "0.000000"
    assert body["max_ai_budget"] is None
    assert body["next_round_context"] is None
    assert body["remaining_ai_budget"] is None
    assert body["budget_exhausted"] is False
    assert body["stagnation_detected"] is False
    assert body["created_at"]
    assert body["updated_at"]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   ", "raw_idea": "A valid idea"},
        {"name": "A valid name", "raw_idea": "   "},
        {"name": "A valid name", "raw_idea": "A valid idea", "status": "APPROVED"},
    ],
)
async def test_create_project_rejects_invalid_payload(
    client: AsyncClient, payload: dict[str, str]
) -> None:
    response = await client.post("/projects", json=payload)

    assert response.status_code == 422


async def test_list_projects_is_persisted_and_deterministically_ordered(
    client: AsyncClient,
) -> None:
    first = await client.post(
        "/projects", json={"name": "First", "raw_idea": "First idea"}
    )
    second = await client.post(
        "/projects", json={"name": "Second", "raw_idea": "Second idea"}
    )

    response = await client.get("/projects")

    assert first.status_code == second.status_code == 201
    assert response.status_code == 200
    created = [first.json(), second.json()]
    expected = sorted(
        created,
        key=lambda project: (project["created_at"], project["id"]),
        reverse=True,
    )
    assert response.json() == expected


async def test_list_projects_supports_pagination(client: AsyncClient) -> None:
    for index in range(3):
        response = await client.post(
            "/projects",
            json={"name": f"Project {index}", "raw_idea": f"Idea {index}"},
        )
        assert response.status_code == 201

    all_projects = await client.get("/projects")
    response = await client.get("/projects", params={"offset": 1, "limit": 1})

    assert all_projects.status_code == 200
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json() == all_projects.json()[1:2]


async def test_get_project(client: AsyncClient) -> None:
    created = await client.post(
        "/projects", json={"name": "Retrievable", "raw_idea": "Persist this idea"}
    )
    project_id = created.json()["id"]

    response = await client.get(f"/projects/{project_id}")

    assert response.status_code == 200
    assert response.json() == created.json()


async def test_get_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/projects/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


async def test_get_project_rejects_malformed_uuid(client: AsyncClient) -> None:
    response = await client.get("/projects/not-a-uuid")

    assert response.status_code == 422


async def test_create_and_update_project_budget(client: AsyncClient) -> None:
    created = await client.post(
        "/projects",
        json={
            "name": "Budgeted",
            "raw_idea": "Bound the evaluation spend",
            "max_ai_budget": "2.500000",
        },
    )
    project_id = created.json()["id"]

    assert created.status_code == 201
    assert created.json()["max_ai_budget"] == "2.500000"
    assert created.json()["remaining_ai_budget"] == "2.500000"

    changed = await client.patch(
        f"/projects/{project_id}/budget", json={"max_ai_budget": "1.250000"}
    )
    cleared = await client.patch(
        f"/projects/{project_id}/budget", json={"max_ai_budget": None}
    )

    assert changed.status_code == 200
    assert changed.json()["max_ai_budget"] == "1.250000"
    assert changed.json()["remaining_ai_budget"] == "1.250000"
    assert cleared.status_code == 200
    assert cleared.json()["max_ai_budget"] is None
    assert cleared.json()["remaining_ai_budget"] is None


async def test_project_budget_rejects_negative_and_unknown_project(
    client: AsyncClient,
) -> None:
    created = await client.post(
        "/projects", json={"name": "Budgeted", "raw_idea": "A valid idea"}
    )

    negative = await client.patch(
        f"/projects/{created.json()['id']}/budget", json={"max_ai_budget": -1}
    )
    unknown = await client.patch(
        f"/projects/{uuid4()}/budget", json={"max_ai_budget": 1}
    )

    assert negative.status_code == 422
    assert unknown.status_code == 404


async def test_save_and_clear_next_round_context(client: AsyncClient) -> None:
    created = await client.post(
        "/projects", json={"name": "Guided", "raw_idea": "A valid idea"}
    )
    project_id = created.json()["id"]

    saved = await client.patch(
        f"/projects/{project_id}/next-round-context",
        json={"next_round_context": "  Priorize operação offline.  "},
    )
    cleared = await client.patch(
        f"/projects/{project_id}/next-round-context",
        json={"next_round_context": None},
    )
    blank = await client.patch(
        f"/projects/{project_id}/next-round-context",
        json={"next_round_context": "   "},
    )
    unknown = await client.patch(
        f"/projects/{uuid4()}/next-round-context",
        json={"next_round_context": "Contexto"},
    )

    assert saved.status_code == 200
    assert saved.json()["next_round_context"] == "Priorize operação offline."
    assert cleared.status_code == 200
    assert cleared.json()["next_round_context"] is None
    assert blank.status_code == 422
    assert unknown.status_code == 404


async def test_create_and_update_agent_execution_plan(client: AsyncClient) -> None:
    created = await client.post(
        "/projects",
        json={
            "name": "Focused",
            "raw_idea": "Go deeper on evidence",
            "agent_plan": {"builder": 0, "researcher": 3, "critic": 2},
        },
    )
    project_id = created.json()["id"]

    changed = await client.patch(
        f"/projects/{project_id}/agent-plan",
        json={"agent_plan": {"builder": 2, "researcher": 1, "critic": 0}},
    )
    all_disabled = await client.patch(
        f"/projects/{project_id}/agent-plan",
        json={"agent_plan": {"builder": 0, "researcher": 0, "critic": 0}},
    )
    too_deep = await client.patch(
        f"/projects/{project_id}/agent-plan",
        json={"agent_plan": {"builder": 4, "researcher": 1, "critic": 1}},
    )
    unknown = await client.patch(
        f"/projects/{uuid4()}/agent-plan",
        json={"agent_plan": {"builder": 1, "researcher": 1, "critic": 1}},
    )

    assert created.status_code == 201
    assert created.json()["agent_plan"] == {
        "builder": 0,
        "researcher": 3,
        "critic": 2,
    }
    assert changed.status_code == 200
    assert changed.json()["agent_plan"] == {
        "builder": 2,
        "researcher": 1,
        "critic": 0,
    }
    assert all_disabled.status_code == 422
    assert too_deep.status_code == 422
    assert unknown.status_code == 404
