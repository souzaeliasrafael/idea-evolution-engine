from importlib.resources import files
import re

from app.domain.enums import AgentType


SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9_-]+$")


class PromptNotFoundError(FileNotFoundError):
    pass


DEFAULT_PROMPT_VERSIONS: dict[AgentType, str] = {
    AgentType.STRUCTURER: "v1",
    AgentType.BUILDER: "v4",
    AgentType.RESEARCHER: "v3",
    AgentType.CRITIC: "v1",
    AgentType.JUDGE: "v3",
    AgentType.IMPROVER: "v1",
    AgentType.PRODUCT_ARCHITECT: "v1",
    AgentType.SOLUTION_ARCHITECT: "v1",
    AgentType.TECHNICAL_CRITIC: "v1",
    AgentType.ROADMAP_PLANNER: "v1",
}


def load_prompt(agent: str, version: str) -> str:
    if not SAFE_PATH_COMPONENT.fullmatch(agent) or not SAFE_PATH_COMPONENT.fullmatch(version):
        raise ValueError("Agent and prompt version must be safe path components")

    prompt_resource = files("prompts").joinpath(agent, f"{version}.md")
    try:
        prompt = prompt_resource.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise PromptNotFoundError(
            f"Prompt not found for agent={agent!r}, version={version!r}"
        ) from exc

    if not prompt:
        raise ValueError(f"Prompt file is empty: {agent}/{version}.md")
    return prompt


def load_default_prompt(agent: AgentType) -> tuple[str, str]:
    version = DEFAULT_PROMPT_VERSIONS[agent]
    return load_prompt(agent.value.lower(), version), version
