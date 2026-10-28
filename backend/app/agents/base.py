from dataclasses import dataclass
import json
from time import perf_counter
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.domain.enums import AgentType
from app.llm.base import LLMProvider, LLMRequest, LLMResponse
from app.llm.prompts import load_prompt


AgentOutput = TypeVar("AgentOutput", bound=BaseModel)


@dataclass(frozen=True)
class LLMAttempt:
    response: LLMResponse | None
    output_json: dict[str, Any] | None
    error: str | None
    execution_time: float


@dataclass(frozen=True)
class AgentResult(Generic[AgentOutput]):
    output: AgentOutput
    attempts: tuple[LLMAttempt, ...]
    prompt_version: str
    input_data: dict[str, Any]


@dataclass(frozen=True)
class AgentRecovery(Generic[AgentOutput]):
    output: AgentOutput
    response: LLMResponse | None
    output_json: dict[str, Any]


class AgentExecutionError(RuntimeError):
    def __init__(self, attempts: tuple[LLMAttempt, ...], input_data: dict[str, Any]):
        super().__init__("Agent did not return a valid typed output")
        self.attempts = attempts
        self.input_data = input_data


class TypedAgent(Generic[AgentOutput]):
    role: AgentType
    prompt_name: str
    output_schema: type[AgentOutput]
    prompt_version = "v1"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        max_attempts: int = 2,
        retry_max_output_tokens: int = 16_384,
        initial_max_output_tokens: int | None = None,
        retry_on_max_output_tokens: bool = True,
        prompt: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.provider = provider
        self.max_attempts = max_attempts
        self.retry_max_output_tokens = retry_max_output_tokens
        self.initial_max_output_tokens = initial_max_output_tokens
        self.retry_on_max_output_tokens = retry_on_max_output_tokens
        self.prompt_version = prompt_version or self.prompt_version
        self.prompt = prompt or load_prompt(self.prompt_name, self.prompt_version)
        if not self.prompt.strip():
            raise ValueError("Agent prompt cannot be blank")

    async def execute(self, input_data: dict[str, Any]) -> AgentResult[AgentOutput]:
        attempts: list[LLMAttempt] = []
        retry_feedback: dict[str, Any] | None = None
        requested_output_tokens = self.initial_max_output_tokens

        for attempt_number in range(1, self.max_attempts + 1):
            started_at = perf_counter()
            response: LLMResponse | None = None
            output_json: dict[str, Any] | None = None
            try:
                request_input = dict(input_data)
                if retry_feedback is not None:
                    request_input["_retry_feedback"] = retry_feedback
                response = await self.provider.generate(
                    self.build_request(
                        request_input,
                        max_output_tokens=requested_output_tokens,
                    )
                )
                if response.finish_reason is not None:
                    raise ValueError(
                        f"Provider response was not completed: {response.finish_reason}"
                    )
                decoded = json.loads(response.content)
                if not isinstance(decoded, dict):
                    raise ValueError("Agent output must be a JSON object")
                output_json = decoded
                output = self.output_schema.model_validate(decoded)
                self.validate_output(output, input_data)
                self.validate_response(output, input_data, response)
            except Exception as exc:
                if output_json is None and response is not None:
                    output_json = {"raw_response": response.content}
                attempts.append(
                    LLMAttempt(
                        response=response,
                        output_json=output_json,
                        error=f"{type(exc).__name__}: {exc}"[:2000],
                        execution_time=perf_counter() - started_at,
                    )
                )
                error_message = f"{type(exc).__name__}: {exc}"[:2000]
                retry_feedback = {
                    "attempt": attempt_number,
                    "previous_error": error_message,
                    "instruction": (
                        "Return one complete JSON object that strictly matches the "
                        "provided schema. Correct the previous error; be concise and "
                        "do not repeat the input."
                    ),
                }
                if response is not None and response.web_sources:
                    retry_feedback["web_sources"] = [
                        source.model_dump(mode="json")
                        for source in response.web_sources
                    ]
                    retry_feedback["instruction"] += (
                        " Reuse the supplied web sources; do not run web search again."
                    )
                if response is not None and response.finish_reason == "max_output_tokens":
                    if not self.retry_on_max_output_tokens:
                        recovery_started_at = perf_counter()
                        try:
                            recovery = await self.recover_truncated_response(
                                input_data, response
                            )
                        except Exception as recovery_exc:
                            attempts.append(
                                LLMAttempt(
                                    response=None,
                                    output_json=None,
                                    error=(
                                        f"{type(recovery_exc).__name__}: {recovery_exc}"
                                    )[:2000],
                                    execution_time=perf_counter() - recovery_started_at,
                                )
                            )
                            break
                        if recovery is not None:
                            attempts.append(
                                LLMAttempt(
                                    response=recovery.response,
                                    output_json=recovery.output_json,
                                    error=None,
                                    execution_time=perf_counter() - recovery_started_at,
                                )
                            )
                            return AgentResult(
                                output=recovery.output,
                                attempts=tuple(attempts),
                                prompt_version=self.prompt_version,
                                input_data=input_data,
                            )
                        break
                    current_limit = requested_output_tokens or int(
                        getattr(self.provider, "max_output_tokens", 4096)
                    )
                    requested_output_tokens = min(
                        max(current_limit * 2, current_limit + 1024),
                        self.retry_max_output_tokens,
                    )
                continue

            attempts.append(
                LLMAttempt(
                    response=response,
                    output_json=output.model_dump(mode="json"),
                    error=None,
                    execution_time=perf_counter() - started_at,
                )
            )
            return AgentResult(
                output=output,
                attempts=tuple(attempts),
                prompt_version=self.prompt_version,
                input_data=input_data,
            )

        raise AgentExecutionError(tuple(attempts), input_data)

    async def recover_truncated_response(
        self, input_data: dict[str, Any], response: LLMResponse
    ) -> AgentRecovery[AgentOutput] | None:
        """Optional agent-specific recovery that must not regenerate a full answer."""

        return None

    def validate_output(
        self, output: AgentOutput, input_data: dict[str, Any]
    ) -> None:
        """Allow an agent to enforce invariants beyond its Pydantic schema."""

    def validate_response(
        self,
        output: AgentOutput,
        input_data: dict[str, Any],
        response: LLMResponse,
    ) -> None:
        """Allow validation that also depends on provider metadata."""

    def build_request(
        self,
        input_data: dict[str, Any],
        *,
        max_output_tokens: int | None = None,
    ) -> LLMRequest:
        return LLMRequest(
            role=self.role.value,
            prompt=self.prompt,
            input_data=input_data,
            output_schema_name=f"{self.role.value.lower()}_output",
            output_schema=self.output_schema.model_json_schema(),
            max_output_tokens=max_output_tokens,
        )
