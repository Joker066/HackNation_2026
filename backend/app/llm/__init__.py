from app.config import Settings

from .base import ImageInput, LLMError, LLMProvider, LLMUsage


def build_provider(settings: Settings) -> LLMProvider:
    """Pick the provider from settings. Add new providers here (e.g. Mistral for EU hosting)."""
    if settings.llm_provider == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings)
    if settings.llm_provider == "fake":
        from .fake import FakeProvider

        return FakeProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")


__all__ = ["ImageInput", "LLMError", "LLMProvider", "LLMUsage", "build_provider"]
