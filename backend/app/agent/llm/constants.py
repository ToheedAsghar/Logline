# --- OpenAI provider error messages ---

ERROR_RUN_TURN_ZERO_CHOICES = "run_turn failed: the model returned zero choices"

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

ERROR_RUN_STRUCTURED_ZERO_CHOICES = "run_structured failed: the model returned zero choices"

ERROR_RUN_STRUCTURED_PARSED_NONE = (
    "run_structured failed: the model's response could not be parsed into {model_name} "
    "(no exception was raised, but .parsed was None)"
)

# --- Usage logging ---

USAGE_LOG_FORMAT = "openai %s usage: prompt=%s completion=%s total=%s"
