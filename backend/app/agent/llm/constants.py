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
