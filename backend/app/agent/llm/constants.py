# --- Shared structured-output error messages ---

ERROR_RUN_STRUCTURED_TRUNCATED = (
    "run_structured failed: model output was truncated before "
    "completing the structured response (length finish reason)"
)

ERROR_RUN_STRUCTURED_CONTENT_FILTERED = (
    "run_structured failed: response was blocked by the content filter"
)

ERROR_RUN_STRUCTURED_VALIDATION_FAILED = (
    "run_structured failed: the model's output didn't validate against {model_name}: {detail}"
)

# --- OpenAI provider error messages ---

ERROR_RUN_TURN_ZERO_CHOICES = "run_turn failed: the model returned zero choices"

ERROR_RUN_STRUCTURED_ZERO_CHOICES = "run_structured failed: the model returned zero choices"

ERROR_RUN_STRUCTURED_PARSED_NONE = (
    "run_structured failed: the model's response could not be parsed into {model_name} "
    "(no exception was raised, but .parsed was None)"
)

# --- Gemini provider error messages ---

ERROR_GEMINI_RUN_TURN_UNSUPPORTED = (
    "GeminiProvider does not implement run_turn. Gemini is wired for structured output only "
    "(run_structured), which is all the reconciliation pipeline uses; the older tool-calling agent "
    "runner remains OpenAI-only."
)

ERROR_GEMINI_TOOL_MESSAGE_UNSUPPORTED = (
    "run_structured failed: GeminiProvider received a role='tool' message, but it does not support "
    "tool calling. Structured-output calls should only carry system/user/assistant messages."
)

ERROR_RUN_STRUCTURED_PROMPT_BLOCKED = (
    "run_structured failed: the prompt was blocked before generation could start (reason: {reason})"
)

ERROR_RUN_STRUCTURED_NO_CANDIDATES = "run_structured failed: the model returned no candidates"

ERROR_RUN_STRUCTURED_EMPTY_TEXT = (
    "run_structured failed: the model returned an empty response body, so there was nothing to "
    "parse into {model_name}"
)

ERROR_GEMINI_API_ERROR = (
    "run_structured failed: the Gemini API request for {model_name} failed (see cause for detail)"
)

# --- Usage logging ---

USAGE_LOG_FORMAT = "openai %s usage: prompt=%s completion=%s total=%s"

GEMINI_USAGE_LOG_FORMAT = "gemini %s usage: prompt=%s candidates=%s total=%s"
