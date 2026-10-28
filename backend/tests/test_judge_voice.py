import json
from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.schemas.judge_chat import JudgeVoiceSessionRead
from app.services import judge_voice


pytestmark = pytest.mark.anyio


async def test_realtime_secret_uses_natural_voice_session_configuration() -> None:
    project_id = UUID("11111111-1111-1111-1111-111111111111")

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/realtime/client_secrets"
        assert request.headers["authorization"] == "Bearer sk-test"
        assert request.headers["openai-safety-identifier"] != str(project_id)
        session = payload["session"]
        assert session["model"] == "gpt-realtime-2.1"
        assert session["audio"]["output"]["voice"] == "marin"
        assert session["audio"]["input"]["turn_detection"] == {
            "type": "semantic_vad",
            "eagerness": "low",
            "create_response": True,
            "interrupt_response": True,
        }
        assert session["tool_choice"] == "required"
        assert session["tools"][0]["name"] == "submit_to_judge_cycle"
        return httpx.Response(200, json={"value": "ek_test", "expires_at": 9999999999})

    settings = Settings(
        _env_file=None,
        openai_api_key="sk-test",
        openai_base_url="https://api.openai.com/v1",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        result = await judge_voice.create_session(
            settings,
            project_id,
            project_name="Projeto teste",
            client=http_client,
        )

    assert result.client_secret == "ek_test"
    assert result.model == "gpt-realtime-2.1"
    assert result.voice == "marin"
    assert result.max_duration_seconds == 600


async def test_voice_session_endpoint_returns_only_ephemeral_secret(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post(
        "/projects",
        json={"name": "Natural voice", "raw_idea": "Talk to the Judge"},
    )
    project_id = created.json()["id"]

    async def fake_create_session(*args: object, **kwargs: object) -> JudgeVoiceSessionRead:
        return JudgeVoiceSessionRead(
            client_secret="ek_short_lived",
            expires_at=9999999999,
            model="gpt-realtime-2.1",
            voice="marin",
            max_duration_seconds=600,
        )

    monkeypatch.setattr(judge_voice, "create_session", fake_create_session)
    response = await client.post(f"/projects/{project_id}/judge-voice/session")

    assert response.status_code == 200
    assert response.json() == {
        "client_secret": "ek_short_lived",
        "expires_at": 9999999999,
        "model": "gpt-realtime-2.1",
        "voice": "marin",
        "max_duration_seconds": 600,
    }
    assert "sk-" not in response.text


async def test_voice_session_respects_project_budget_before_minting_token(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post(
        "/projects",
        json={"name": "No voice budget", "raw_idea": "An idea", "max_ai_budget": "0"},
    )
    called = False

    async def fake_create_session(*args: object, **kwargs: object) -> JudgeVoiceSessionRead:
        nonlocal called
        called = True
        raise AssertionError("The provider must not be called")

    monkeypatch.setattr(judge_voice, "create_session", fake_create_session)
    response = await client.post(
        f"/projects/{created.json()['id']}/judge-voice/session"
    )

    assert response.status_code == 409
    assert called is False
