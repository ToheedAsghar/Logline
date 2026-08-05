"""
Tests for provider resolution (app/agent/llm/__init__.py).

Which provider serves a call is resolved as: the user's `preferred_llm_provider`, else the global
`LLM_PROVIDER` setting, else "openai". The `user` argument is optional so that every pre-existing
caller -- notably `app/agent/runner.py` -- keeps working untouched.

These tests build `User` objects directly rather than through the database: resolution is pure
attribute reading, and going through a session would test SQLAlchemy rather than the resolution
rules.
"""

import pytest

from app.agent.llm import DEFAULT_PROVIDER, get_llm_provider, resolve_provider_name
from app.agent.llm.gemini_provider import GeminiProvider
from app.agent.llm.openai_provider import OpenAIProvider
from app.auth.models import User


@pytest.fixture
def global_openai(monkeypatch):
    from app.agent.llm import _provider_cache, settings

    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-openai-key")
    monkeypatch.setattr(settings, "gemini_api_key", "test-gemini-key")
    # Providers are cached module-globally by (name, model, api_key) -- clear so each test starts
    # from a clean cache instead of possibly reusing an instance a prior test built.
    _provider_cache.clear()
    return settings


class TestResolveProviderName:
    def test_no_user_falls_back_to_global_setting(self, global_openai):
        assert resolve_provider_name() == "openai"

    def test_none_user_falls_back_to_global_setting(self, global_openai):
        assert resolve_provider_name(None) == "openai"

    def test_user_without_preference_falls_back_to_global_setting(self, global_openai):
        assert resolve_provider_name(User(email="a@b.com", preferred_llm_provider=None)) == "openai"

    def test_user_preference_wins_over_global_setting(self, global_openai):
        user = User(email="a@b.com", preferred_llm_provider="gemini")

        assert resolve_provider_name(user) == "gemini"

    def test_global_setting_applies_when_user_has_no_preference(self, global_openai, monkeypatch):
        monkeypatch.setattr(global_openai, "llm_provider", "gemini")

        assert resolve_provider_name(User(email="a@b.com")) == "gemini"

    def test_preference_is_case_insensitive(self, global_openai):
        assert resolve_provider_name(User(email="a@b.com", preferred_llm_provider="GEMINI")) == "gemini"

    def test_empty_global_setting_falls_back_to_default(self, global_openai, monkeypatch):
        """An unset LLM_PROVIDER must not resolve to "" and blow up as an unknown provider."""
        monkeypatch.setattr(global_openai, "llm_provider", "")

        assert resolve_provider_name() == DEFAULT_PROVIDER == "openai"


class TestGetLLMProvider:
    def test_default_is_openai(self, global_openai):
        """Existing behaviour must not change: no user, default config, still OpenAI."""
        provider = get_llm_provider()

        assert isinstance(provider, OpenAIProvider)

    def test_user_preferring_gemini_gets_gemini(self, global_openai):
        provider = get_llm_provider(User(email="a@b.com", preferred_llm_provider="gemini"))

        assert isinstance(provider, GeminiProvider)

    def test_user_preferring_openai_gets_openai_even_when_global_is_gemini(self, global_openai, monkeypatch):
        monkeypatch.setattr(global_openai, "llm_provider", "gemini")

        provider = get_llm_provider(User(email="a@b.com", preferred_llm_provider="openai"))

        assert isinstance(provider, OpenAIProvider)

    def test_gemini_provider_uses_gemini_model_not_llm_model(self, global_openai, monkeypatch):
        """`llm_model` defaults to an OpenAI model name; sending it to Gemini would fail every call."""
        monkeypatch.setattr(global_openai, "llm_model", "gpt-5-mini")
        monkeypatch.setattr(global_openai, "gemini_model", "gemini-2.5-flash")

        provider = get_llm_provider(User(email="a@b.com", preferred_llm_provider="gemini"))

        assert provider.model == "gemini-2.5-flash"

    def test_unknown_provider_raises(self, global_openai):
        user = User(email="a@b.com", preferred_llm_provider="llama")

        with pytest.raises(NotImplementedError, match="llama"):
            get_llm_provider(user)

    def test_unknown_provider_error_lists_supported_providers(self, global_openai):
        with pytest.raises(NotImplementedError, match="gemini"):
            get_llm_provider(User(email="a@b.com", preferred_llm_provider="llama"))


class TestGetLLMProviderCaching:
    """A fresh provider means a fresh SDK client, which means a fresh connection pool -- calling
    `get_llm_provider()` on every request would open a new TCP/TLS connection per call and never
    close the old one. Instances must be reused across calls for the same (provider, model, api_key).
    """

    def test_repeated_calls_return_the_same_instance(self, global_openai):
        first = get_llm_provider()
        second = get_llm_provider()

        assert first is second

    def test_different_users_preferring_the_same_provider_share_an_instance(self, global_openai):
        alice = User(email="alice@b.com", preferred_llm_provider="gemini")
        bob = User(email="bob@b.com", preferred_llm_provider="gemini")

        assert get_llm_provider(alice) is get_llm_provider(bob)

    def test_different_providers_get_different_instances(self, global_openai):
        openai_provider = get_llm_provider(User(email="a@b.com", preferred_llm_provider="openai"))
        gemini_provider = get_llm_provider(User(email="a@b.com", preferred_llm_provider="gemini"))

        assert openai_provider is not gemini_provider

    def test_changed_settings_produce_a_new_instance_not_a_stale_cached_one(self, global_openai, monkeypatch):
        """Regression guard for the cache key itself: keying on provider name alone would return a
        stale instance built from a previous model/api_key after settings change (as happens between
        test runs via monkeypatch, and in principle across a config reload)."""
        first = get_llm_provider(User(email="a@b.com", preferred_llm_provider="gemini"))

        monkeypatch.setattr(global_openai, "gemini_model", "gemini-3.0-pro")
        second = get_llm_provider(User(email="a@b.com", preferred_llm_provider="gemini"))

        assert first is not second
        assert second.model == "gemini-3.0-pro"
