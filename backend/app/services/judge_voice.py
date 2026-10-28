from hashlib import sha256
from uuid import UUID

import httpx

from app.core.config import Settings
from app.llm.providers.http import (
    HTTPJSONClient,
    ProviderConfigurationError,
    ProviderRequestError,
    require_api_key,
)
from app.schemas.judge_chat import JudgeVoiceSessionRead


async def create_session(
    settings: Settings,
    project_id: UUID,
    *,
    project_name: str,
    client: httpx.AsyncClient | None = None,
) -> JudgeVoiceSessionRead:
    if not settings.voice_realtime_enabled:
        raise ProviderConfigurationError("Natural voice is disabled")
    api_key = require_api_key(
        settings.openai_api_key.get_secret_value()
        if settings.openai_api_key is not None
        else None,
        "OPENAI_API_KEY",
    )
    body = await HTTPJSONClient(
        base_url=settings.openai_base_url,
        timeout_seconds=settings.llm_request_timeout_seconds,
        client=client,
    ).post(
        "/realtime/client_secrets",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Safety-Identifier": _safety_identifier(project_id),
        },
        payload={
            "session": {
                "type": "realtime",
                "model": settings.voice_realtime_model,
                "output_modalities": ["audio"],
                "instructions": _instructions(project_name),
                "audio": {
                    "input": {
                        "turn_detection": {
                            "type": "semantic_vad",
                            "eagerness": "low",
                            "create_response": True,
                            "interrupt_response": True,
                        }
                    },
                    "output": {"voice": settings.voice_realtime_voice},
                },
                "tools": [_judge_cycle_tool()],
                "tool_choice": "required",
            }
        },
        provider_name="OpenAI Realtime",
    )
    secret = body.get("value")
    if not isinstance(secret, str) or not secret.strip():
        raise ProviderRequestError(
            "OpenAI Realtime returned no ephemeral client secret"
        )
    expires_at = body.get("expires_at")
    return JudgeVoiceSessionRead(
        client_secret=secret,
        expires_at=expires_at if isinstance(expires_at, int) else None,
        model=settings.voice_realtime_model,
        voice=settings.voice_realtime_voice,
        max_duration_seconds=settings.voice_realtime_max_session_seconds,
    )


def _safety_identifier(project_id: UUID) -> str:
    return sha256(f"idea-evolution-project:{project_id}".encode()).hexdigest()


def _instructions(project_name: str) -> str:
    return f"""
Você é a interface de voz do Judge do projeto {project_name!r}.
Converse sempre em português brasileiro, com voz calorosa, natural, calma e
objetiva. Espere o usuário concluir o raciocínio; não o apresse e aceite
interrupções naturalmente.

Para TODA fala substantiva do usuário, chame obrigatoriamente a ferramenta
submit_to_judge_cycle uma única vez. No argumento message, preserve fielmente
o sentido e os detalhes da fala. Não avalie a ideia por conta própria, não
invente score, confiança ou decisão e não antecipe a resposta enquanto a
ferramenta estiver executando.

Depois que a ferramenta retornar, explique oralmente o resultado de forma
conversacional e concisa. Preserve exatamente decisão, score e confiança
recebidos. Destaque o principal motivo e o próximo passo. Evite listas longas,
linguagem burocrática e frases como "como uma inteligência artificial".
""".strip()


def _judge_cycle_tool() -> dict[str, object]:
    return {
        "type": "function",
        "name": "submit_to_judge_cycle",
        "description": (
            "Envia a fala completa do usuário para um ciclo dos agentes do projeto "
            "e devolve a decisão oficial do Judge."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": (
                        "A fala do usuário em português, preservando todos os detalhes "
                        "úteis para os agentes."
                    ),
                }
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    }
