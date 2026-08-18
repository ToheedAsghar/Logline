"""Tests for the redaction processors (app/core/redaction.py) and the logging pipeline they run in
(app/core/logging.py).

Every test checks that a fake secret string is actually gone from the output, not just that its field got
renamed.
"""

import json
import logging

from app.core.logging import configure_logging
from app.core.redaction import REDACTED_MARKER, redact_forbidden_fields, scan_for_leak_patterns

A_FAKE_OAUTH_STATE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJwdXJwb3NlIjoiZmFrZSJ9.fakefakefakefake"
A_FAKE_STRIPE_TOKEN = "live_YWNjdF9GQUtFVE9LRU5ET05PVFVTRQ"
A_FAKE_BEARER_TOKEN = "Bearer sk-fake-not-a-real-token-1234567890"
A_FAKE_OAUTH_CALLBACK_URL = (
    "http://localhost:8000/auth/google/callback?state=" + A_FAKE_OAUTH_STATE_JWT + "&code=fake_code_value"
)
A_FAKE_HOME_PATH = "/Users/fake-user/Documents/projects/logline/backend"
A_FAKE_LINUX_HOME_PATH = "/home/deploy/projects/logline/backend"
A_FAKE_ROOT_PATH = "/root/.config/logline/secrets.json"
FAKE_EVIDENCE = (
    f"context | urls: https://accounts.google.com/...&state={A_FAKE_OAUTH_STATE_JWT} | "
    f"stripe: {A_FAKE_STRIPE_TOKEN} | project: {A_FAKE_HOME_PATH}"
)


class TestRedactForbiddenFields:
    def test_leaves_ordinary_fields_untouched(self):
        event_dict = {"event": "draft generated", "entry_count": 4, "user_id": 7}
        assert redact_forbidden_fields(None, "info", dict(event_dict)) == event_dict

    def test_redacts_a_top_level_forbidden_field(self):
        event_dict = {"event": "llm call", "evidence_text": f"context | urls: {A_FAKE_OAUTH_STATE_JWT}"}
        result = redact_forbidden_fields(None, "info", event_dict)
        assert result["evidence_text"] == REDACTED_MARKER
        assert A_FAKE_OAUTH_STATE_JWT not in str(result)

    def test_matching_is_case_insensitive(self):
        event_dict = {"Window_Title": "Inbox - someone@example.com - Gmail"}
        result = redact_forbidden_fields(None, "info", event_dict)
        assert result["Window_Title"] == REDACTED_MARKER

    def test_redacts_a_forbidden_field_nested_inside_a_dict(self):
        event_dict = {"entry": {"evidence_text": f"stripe invoice: {A_FAKE_STRIPE_TOKEN}"}, "entry_id": 3}
        result = redact_forbidden_fields(None, "info", event_dict)
        assert result["entry"]["evidence_text"] == REDACTED_MARKER
        assert result["entry_id"] == 3
        assert A_FAKE_STRIPE_TOKEN not in str(result)

    def test_redacts_a_forbidden_field_nested_inside_a_list_of_dicts(self):
        event_dict = {"messages": [{"role": "user", "content": "some prompt body"}]}
        result = redact_forbidden_fields(None, "info", event_dict)
        assert result["messages"] == REDACTED_MARKER

    def test_redacts_a_bearer_token_regardless_of_field_alias(self):
        for field in ("token", "authorization", "bearer_token", "raw_token", "access_token"):
            event_dict = {field: A_FAKE_BEARER_TOKEN}
            result = redact_forbidden_fields(None, "info", event_dict)
            assert result[field] == REDACTED_MARKER
            assert A_FAKE_BEARER_TOKEN not in str(result)

    def test_redacts_near_miss_aliases_found_by_adversarial_review(self):
        for field in ("evidence_blob", "raw_evidence", "window_titles", "bearer", "secret_token", "id_token"):
            event_dict = {field: A_FAKE_BEARER_TOKEN}
            result = redact_forbidden_fields(None, "info", event_dict)
            assert result[field] == REDACTED_MARKER

    def test_redacts_a_forbidden_field_whose_value_is_a_tuple_or_set(self):
        result = redact_forbidden_fields(None, "info", {"evidence_text": (A_FAKE_STRIPE_TOKEN,)})
        assert result["evidence_text"] == REDACTED_MARKER
        result = redact_forbidden_fields(None, "info", {"evidence_text": {A_FAKE_STRIPE_TOKEN}})
        assert result["evidence_text"] == REDACTED_MARKER

    def test_a_fabricated_evidence_leak_shaped_payload_never_survives(self):
        """Mimics the real evidence.py leak: OAuth state, a Stripe-style token, and a raw path, all inside one
        evidence_text field nested in an LLM message list.
        """
        event_dict = {
            "event": "describe_entry called",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"context | urls: https://accounts.google.com/...&state={A_FAKE_OAUTH_STATE_JWT} | "
                        f"stripe: {A_FAKE_STRIPE_TOKEN}"
                    ),
                }
            ],
            "evidence_text": "project: /Users/fake-user/Documents/projects/logline",
        }
        result = redact_forbidden_fields(None, "info", event_dict)
        rendered = str(result)
        assert A_FAKE_OAUTH_STATE_JWT not in rendered
        assert A_FAKE_STRIPE_TOKEN not in rendered
        assert "/Users/fake-user" not in rendered


class TestScanForLeakPatterns:
    def test_must_catch_jwt_shaped_token(self):
        result = scan_for_leak_patterns(None, "info", {"event": f"token: {A_FAKE_OAUTH_STATE_JWT}"})
        assert A_FAKE_OAUTH_STATE_JWT not in result["event"]
        assert REDACTED_MARKER in result["event"]

    def test_must_catch_oauth_query_param(self):
        result = scan_for_leak_patterns(None, "info", {"event": f"GET {A_FAKE_OAUTH_CALLBACK_URL} HTTP/1.1"})
        assert "state=" not in result["event"]
        assert "code=" not in result["event"]
        assert A_FAKE_OAUTH_STATE_JWT not in result["event"]

    def test_must_catch_local_home_path(self):
        result = scan_for_leak_patterns(None, "info", {"event": f"project: {A_FAKE_HOME_PATH}"})
        assert A_FAKE_HOME_PATH not in result["event"]
        assert "/Users/fake-user" not in result["event"]

    def test_must_catch_linux_and_root_home_paths(self):
        result_linux = scan_for_leak_patterns(None, "info", {"event": f"project: {A_FAKE_LINUX_HOME_PATH}"})
        assert A_FAKE_LINUX_HOME_PATH not in result_linux["event"]
        assert "/home/deploy" not in result_linux["event"]
        assert REDACTED_MARKER in result_linux["event"]

        result_root = scan_for_leak_patterns(None, "info", {"event": f"config: {A_FAKE_ROOT_PATH}"})
        assert A_FAKE_ROOT_PATH not in result_root["event"]
        assert "/root" not in result_root["event"]
        assert REDACTED_MARKER in result_root["event"]

    def test_must_catch_bare_root_home_path(self):
        result = scan_for_leak_patterns(None, "info", {"event": "HOME=/root"})
        assert "/root" not in result["event"]
        assert REDACTED_MARKER in result["event"]

    def test_must_catch_stripe_style_key(self):
        result = scan_for_leak_patterns(
            None, "info", {"event": f"invoice.stripe.com/i/acct_x/{A_FAKE_STRIPE_TOKEN}"}
        )
        assert A_FAKE_STRIPE_TOKEN not in result["event"]

    def test_all_four_shapes_in_one_message_all_redacted(self):
        result = scan_for_leak_patterns(None, "info", {"event": FAKE_EVIDENCE})
        rendered = result["event"]
        assert A_FAKE_OAUTH_STATE_JWT not in rendered
        assert A_FAKE_STRIPE_TOKEN not in rendered
        assert A_FAKE_HOME_PATH not in rendered

    def test_must_not_redact_a_normal_relative_project_path(self):
        text = "backend/app/agent/reconciliation/evidence.py"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_a_normal_github_api_url(self):
        text = "https://api.github.com/repos/ToheedAsghar/logline/pulls/61"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_a_web_route_starting_with_home(self):
        text = "navigated to /homepage"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_a_plain_uuid(self):
        text = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_a_semver_pin(self):
        text = "authlib==1.7.2"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_an_iso_timestamp(self):
        text = "2026-08-12T05:48:17.567264Z"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_a_python_module_path(self):
        text = "app.agent.reconciliation.description"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_a_docker_image_tag(self):
        text = "ghcr.io/github/github-mcp-server:latest"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_a_benign_query_param_containing_the_substring_token(self):
        text = "?page_token=abc123"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_must_not_redact_a_commit_sha(self):
        text = "b81b895e97641c316dff36462f7336ff33d"
        result = scan_for_leak_patterns(None, "info", {"event": text})
        assert result["event"] == text

    def test_a_fabricated_evidence_leak_shaped_payload_never_survives(self):
        event_dict = {
            "event": "describe_entry called",
            "messages": [{"role": "user", "content": FAKE_EVIDENCE}],
        }
        result = scan_for_leak_patterns(None, "info", event_dict)
        rendered = str(result)
        assert A_FAKE_OAUTH_STATE_JWT not in rendered
        assert A_FAKE_STRIPE_TOKEN not in rendered
        assert A_FAKE_HOME_PATH not in rendered

    def test_redacts_a_leak_shape_nested_inside_a_tuple(self):
        """A secret inside a tuple, e.g. `extra={"data": (evidence_text,)}`, should still get redacted."""
        result = scan_for_leak_patterns(None, "info", {"data": (A_FAKE_OAUTH_STATE_JWT,)})
        assert A_FAKE_OAUTH_STATE_JWT not in str(result)

    def test_redacts_a_leak_shape_nested_inside_a_set(self):
        result = scan_for_leak_patterns(None, "info", {"data": {A_FAKE_STRIPE_TOKEN}})
        assert A_FAKE_STRIPE_TOKEN not in str(result)


class TestRedactionSignal:
    def test_field_denylist_redaction_emits_exactly_one_signal(self, capsys):
        configure_logging()
        redact_forbidden_fields(None, "info", {"evidence_text": FAKE_EVIDENCE})
        lines = [line for line in capsys.readouterr().out.splitlines() if "redaction_triggered" in line]
        assert len(lines) == 1
        assert json.loads(lines[0])["layer"] == "field_denylist"

    def test_content_scan_redaction_emits_exactly_one_signal(self, capsys):
        configure_logging()
        scan_for_leak_patterns(None, "info", {"event": FAKE_EVIDENCE})
        lines = [line for line in capsys.readouterr().out.splitlines() if "redaction_triggered" in line]
        assert len(lines) == 1
        assert json.loads(lines[0])["layer"] == "content_scan"

    def test_no_signal_when_nothing_is_redacted(self, capsys):
        configure_logging()
        redact_forbidden_fields(None, "info", {"event": "draft generated", "entry_count": 4})
        scan_for_leak_patterns(None, "info", {"event": "draft generated", "entry_count": 4})
        out = capsys.readouterr().out
        assert "redaction_triggered" not in out

    def test_signal_processing_does_not_recurse_into_itself(self):
        signal_shaped_event = {
            "event": "redaction_triggered",
            "layer": "field_denylist",
            "matched": ["evidence_text"],
            "_is_redaction_signal": True,
        }
        result_layer2 = redact_forbidden_fields(None, "warning", dict(signal_shaped_event))
        result_layer3 = scan_for_leak_patterns(None, "warning", dict(signal_shaped_event))
        assert result_layer2 == signal_shaped_event
        assert result_layer3 == signal_shaped_event

    def test_signal_payload_never_contains_the_matched_value(self, capsys):
        configure_logging()
        redact_forbidden_fields(None, "info", {"evidence_text": FAKE_EVIDENCE})
        out = capsys.readouterr().out
        assert A_FAKE_OAUTH_STATE_JWT not in out
        assert A_FAKE_STRIPE_TOKEN not in out
        assert '"event": "redaction_triggered"' in out


class TestFullPipelineIntegration:
    def test_a_real_existing_call_site_produces_valid_json(self, capsys):
        configure_logging()
        logging.getLogger("app.remote_fetch.mcp.connection").warning(
            "could not connect '%s' MCP server: %s", "github", "connection refused"
        )
        out = capsys.readouterr().out.strip()
        parsed = json.loads(out)
        assert parsed["level"] == "warning"
        assert "github" in parsed["event"]

    def test_percent_s_interpolated_evidence_leak_is_redacted_end_to_end(self, capsys):
        """A %s-style stdlib log call has no field name for Layer 2 to match, so Layer 3 must catch it by
        scanning the rendered text instead.
        """
        configure_logging()
        logging.getLogger("app.agent.reconciliation.description").info(
            "evidence for entry: %s", FAKE_EVIDENCE
        )
        out = capsys.readouterr().out
        assert A_FAKE_OAUTH_STATE_JWT not in out
        assert A_FAKE_STRIPE_TOKEN not in out
        assert A_FAKE_HOME_PATH not in out

    def test_exc_info_traceback_text_is_redacted_end_to_end(self, capsys):
        """logger.exception() carries a raw traceback that neither redaction layer can read directly.
        format_exc_info turns it into plain text first, so a secret in an exception message, like a URL
        with a token in it, still gets caught.
        """
        configure_logging()
        logger = logging.getLogger("app.remote_fetch.orchestrator")
        try:
            raise ConnectionError(
                f"Failed to fetch https://github.com/login/oauth/access_token?client_id=abc"
                f"&state={A_FAKE_OAUTH_STATE_JWT} : connection reset by peer"
            )
        except ConnectionError:
            logger.exception("remote_fetch_source_raised", extra={"source": "github"})
        out = capsys.readouterr().out
        assert A_FAKE_OAUTH_STATE_JWT not in out

    def test_exc_info_true_kwarg_is_also_redacted(self, capsys):
        configure_logging()
        logger = logging.getLogger("app.auth.routers")
        try:
            raise RuntimeError(f"token leak: {A_FAKE_STRIPE_TOKEN}")
        except RuntimeError:
            logger.error("email_send_failed", extra={"user_id": 1}, exc_info=True)
        out = capsys.readouterr().out
        assert A_FAKE_STRIPE_TOKEN not in out
