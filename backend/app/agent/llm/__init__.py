"""Factory for the configured LLMProvider.

Nothing outside this package should import `openai` or `anthropic` directly —
callers ask for a provider via `get_llm_provider()` and talk to it only through
the `LLMProvider` interface in `app.agent.llm.base`.
"""

from app.agent.llm.base import LLMProvider
from app.config import settings


def get_llm_provider() -> LLMProvider:
    provider = settings.llm_provider.lower()

    if provider == "openai":
        from app.agent.llm.openai_provider import OpenAIProvider

        return OpenAIProvider(model=settings.llm_model, api_key=settings.openai_api_key)

    raise NotImplementedError(
        f"LLM_PROVIDER={provider!r} is not implemented. Only 'openai' is currently "
        "supported — add a provider module under app/agent/llm/ and wire it in here."
    )
