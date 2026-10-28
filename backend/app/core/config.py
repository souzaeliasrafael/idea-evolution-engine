from functools import lru_cache
from decimal import Decimal
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = "Idea Evolution Engine"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = Field(default="sqlite+aiosqlite:///./iee.db")
    llm_provider: str = "mock"
    llm_model: str = "mock-llm-v1"
    llm_input_cost_per_million: Decimal = Field(default=Decimal("0"), ge=0)
    llm_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    llm_output_cost_per_million: Decimal = Field(default=Decimal("0"), ge=0)
    structurer_provider: str | None = None
    structurer_model: str | None = None
    structurer_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    structurer_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    structurer_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    builder_provider: str | None = None
    builder_model: str | None = None
    builder_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    builder_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    builder_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    researcher_provider: str | None = None
    researcher_model: str | None = None
    researcher_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    researcher_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    researcher_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    research_web_enabled: bool = True
    research_web_max_calls: int = Field(default=2, ge=1, le=10)
    research_web_context_size: Literal["low", "medium", "high"] = "low"
    critic_provider: str | None = None
    critic_model: str | None = None
    critic_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    critic_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    critic_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    judge_provider: str | None = None
    judge_model: str | None = None
    judge_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    judge_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    judge_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    improver_provider: str | None = None
    improver_model: str | None = None
    improver_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    improver_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    improver_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    product_architect_provider: str | None = None
    product_architect_model: str | None = None
    product_architect_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    product_architect_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    product_architect_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    solution_architect_provider: str | None = None
    solution_architect_model: str | None = None
    solution_architect_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    solution_architect_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    solution_architect_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    technical_critic_provider: str | None = None
    technical_critic_model: str | None = None
    technical_critic_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    technical_critic_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    technical_critic_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    roadmap_planner_provider: str | None = None
    roadmap_planner_model: str | None = None
    roadmap_planner_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    roadmap_planner_cached_input_cost_per_million: Decimal | None = Field(default=None, ge=0)
    roadmap_planner_output_cost_per_million: Decimal | None = Field(default=None, ge=0)
    llm_max_attempts: int = Field(default=2, ge=1, le=3)
    llm_request_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=131_072)
    llm_retry_max_output_tokens: int = Field(default=16384, ge=256, le=131_072)
    builder_max_output_tokens: int = Field(default=8192, ge=1024, le=131_072)
    adaptive_agent_depth_enabled: bool = True
    adaptive_depth_score_threshold: int = Field(default=75, ge=0, le=100)
    adaptive_depth_confidence_threshold: float = Field(default=0.70, ge=0, le=1)
    allow_unpriced_cloud_models: bool = False
    openai_api_key: SecretStr | None = None
    openai_admin_key: SecretStr | None = None
    openai_billing_project_ids: str = ""
    openai_web_search_cost_per_call: Decimal = Field(
        default=Decimal("0.01"), ge=0
    )
    openai_base_url: str = "https://api.openai.com/v1"
    voice_realtime_enabled: bool = True
    voice_realtime_model: str = "gpt-realtime-2.1"
    voice_realtime_voice: Literal[
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    ] = "marin"
    voice_realtime_max_session_seconds: int = Field(default=600, ge=60, le=3600)
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"
    gemini_api_key: SecretStr | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    openai_compatible_api_key: SecretStr | None = None
    openai_compatible_base_url: str = "http://localhost:11434/v1"
    max_rounds: int = Field(default=5, ge=1, le=50)
    frontend_origin: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
