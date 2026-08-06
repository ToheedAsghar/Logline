"""Tests for startup validation in app/config.py.

`_require_supported_llm_provider` is called at module import time, right after `settings` is built,
so an invalid `LLM_PROVIDER` fails the process at boot rather than at first reconciliation call.
"""

import pytest

from app.config import _require_supported_llm_provider


class TestRequireSupportedLLMProvider:
    def test_openai_is_accepted(self):
        _require_supported_llm_provider("openai")

    def test_gemini_is_accepted(self):
        _require_supported_llm_provider("gemini")

    def test_accepted_values_are_case_insensitive(self):
        _require_supported_llm_provider("OpenAI")

    def test_unknown_provider_raises(self):
        with pytest.raises(RuntimeError, match="llama"):
            _require_supported_llm_provider("llama")

    def test_error_lists_supported_providers(self):
        with pytest.raises(RuntimeError, match="gemini"):
            _require_supported_llm_provider("llama")
