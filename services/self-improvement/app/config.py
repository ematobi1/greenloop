"""Self-improvement settings. Execution of proposed code is off unless explicitly enabled,
and even then stays blocked until Slice B gates 1-3 are approved (see runner.py)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class SelfImprovementSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    self_improvement_execution_enabled: bool = False
