"""Provider registry built from settings.

Anthropic is registered when ANTHROPIC_API_KEY is set; Ollama when OLLAMA_MODEL is
set. With nothing configured the registry is empty and chat answers
AI_NOT_CONFIGURED instead of failing at startup.
"""

from app.ai.errors import AiError
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.base import ModelProvider, ProviderConfig
from app.ai.providers.ollama import OllamaProvider
from app.core.config import Settings


class ProviderRegistry:
    def __init__(self, providers: dict[str, ModelProvider], default: str) -> None:
        self._providers = providers
        self.default_name = default

    @property
    def names(self) -> list[str]:
        return list(self._providers)

    def get(self, name: str | None = None) -> ModelProvider:
        if not self._providers:
            raise AiError("not_configured")
        provider = self._providers.get(name or self.default_name)
        if provider is None:
            raise AiError("unknown_provider" if name else "not_configured")
        return provider


def build_registry(settings: Settings) -> ProviderRegistry:
    def config(name: str, model: str) -> ProviderConfig:
        return ProviderConfig(
            name=name,
            model=model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        )

    providers: dict[str, ModelProvider] = {}
    if settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value():
        providers["anthropic"] = AnthropicProvider(
            config("anthropic", settings.chat_model),
            api_key=settings.anthropic_api_key,
            effort=settings.anthropic_effort,
        )
    if settings.ollama_model:
        providers["ollama"] = OllamaProvider(
            config("ollama", settings.ollama_model), base_url=settings.ollama_base_url
        )
    return ProviderRegistry(providers, settings.ai_default_provider)
