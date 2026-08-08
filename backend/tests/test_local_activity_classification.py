"""Tests for Pass 1 classification (app/local_activity/classification.py).

Pure logic, no I/O -- every case runs against plain keyword arguments, the same shape `_gather_evidence`
extracts from a `LocalSession` row. Coverage follows the rule priority order (Idle, Meeting, Code Review,
Documentation, Comms, Coding, Admin) and the two things that must never happen: a classifiable session
falling through to the wrong category, and a malformed or missing `context_detail` crashing instead of
degrading to a later rule.
"""

import json

from app.local_activity.classification import SessionCategory, classify_session

VSCODE_BUNDLE_ID = "com.microsoft.VSCode"
TERMINAL_BUNDLE_ID = "com.googlecode.iterm2"
SLACK_BUNDLE_ID = "com.tinyspeck.slackmacgap"
WHATSAPP_BUNDLE_ID = "net.whatsapp.WhatsApp"
CHROME_BUNDLE_ID = "com.google.Chrome"
UNKNOWN_BUNDLE_ID = "com.example.SomeRandomApp"
LOGINWINDOW_BUNDLE_ID = "com.apple.loginwindow"
SECURITY_AGENT_BUNDLE_ID = "com.apple.SecurityAgent"


def _detail(**kwargs) -> str:
    return json.dumps(kwargs)


def _classify(
    bundle_id=CHROME_BUNDLE_ID, window_title=None, project_path=None, context_detail=None
):
    return classify_session(
        bundle_id=bundle_id, window_title=window_title, project_path=project_path, context_detail=context_detail
    )


class TestIdle:
    def test_loginwindow_bundle_classifies_as_idle(self):
        result = _classify(bundle_id=LOGINWINDOW_BUNDLE_ID)

        assert result.category == SessionCategory.idle

    def test_security_agent_bundle_classifies_as_idle(self):
        result = _classify(bundle_id=SECURITY_AGENT_BUNDLE_ID)

        assert result.category == SessionCategory.idle

    def test_idle_takes_priority_over_every_other_rule(self):
        """A locked screen means nothing else in context_detail/window_title reflects real activity,
        whatever it happens to contain -- idle must win even against a signal that would otherwise
        classify as Meeting, the next-highest-priority rule."""
        result = _classify(
            bundle_id=LOGINWINDOW_BUNDLE_ID,
            window_title="Meet - Design Review",
            context_detail=_detail(is_meeting=True, meeting_name="Design Review"),
        )

        assert result.category == SessionCategory.idle
        assert result.meeting_name is None

    def test_idle_bundle_with_project_path_still_classifies_as_idle(self):
        result = _classify(bundle_id=LOGINWINDOW_BUNDLE_ID, project_path="/Users/dev/logline")

        assert result.category == SessionCategory.idle


class TestMeeting:
    def test_context_detail_is_meeting_true_classifies_as_meeting(self):
        result = _classify(context_detail=_detail(is_meeting=True, meeting_name="Standup"))

        assert result.category == SessionCategory.meeting
        assert result.meeting_name == "Standup"

    def test_context_detail_is_meeting_true_with_no_name_leaves_meeting_name_none(self):
        result = _classify(context_detail=_detail(is_meeting=True))

        assert result.category == SessionCategory.meeting
        assert result.meeting_name is None

    def test_explicit_is_meeting_false_is_trusted_and_not_overridden_by_the_url_fallback(self):
        """An explicit `is_meeting: false` from the tracker is a real judgment, not a missing signal -- the
        regex fallback exists only for when the key is absent entirely, not to second-guess an explicit
        False."""
        result = _classify(context_detail=_detail(is_meeting=False, url="https://meet.google.com/abc-defg-hij"))

        assert result.category != SessionCategory.meeting

    def test_meet_title_prefix_fallback_when_context_detail_absent(self):
        """A Meet tab's processed title reads "Meet - <name>", not the URL -- see `tracker/context/meet.py`."""
        result = _classify(window_title="Meet - Design Review", context_detail=None)

        assert result.category == SessionCategory.meeting

    def test_meet_url_text_fallback_when_context_detail_absent(self):
        result = _classify(window_title="https://meet.google.com/abc-defg-hij", context_detail=None)

        assert result.category == SessionCategory.meeting

    def test_a_title_merely_starting_with_meeting_is_not_treated_as_meet(self):
        """"Meeting" must not match the "Meet" word-boundary prefix check."""
        result = _classify(window_title="Meeting Notes.docx", context_detail=None)

        assert result.category != SessionCategory.meeting

    def test_zoom_url_fallback(self):
        result = _classify(window_title="Zoom Meeting", context_detail=_detail(url="https://zoom.us/j/123"))

        assert result.category == SessionCategory.meeting

    def test_teams_url_fallback(self):
        result = _classify(context_detail=_detail(url="https://teams.microsoft.com/l/meetup-join/abc"))

        assert result.category == SessionCategory.meeting

    def test_meeting_takes_priority_over_a_comms_bundle_id(self):
        """A native Slack huddle-style app that is somehow also flagged is_meeting should still classify as a
        meeting -- Meeting is checked before Comms, per the rule table's fixed priority order."""
        result = _classify(bundle_id=SLACK_BUNDLE_ID, context_detail=_detail(is_meeting=True))

        assert result.category == SessionCategory.meeting


class TestCodeReview:
    def test_github_pull_url_classifies_as_code_review(self):
        result = _classify(context_detail=_detail(url="https://github.com/ToheedAsghar/Logline/pull/58"))

        assert result.category == SessionCategory.code_review

    def test_gitlab_merge_request_url_classifies_as_code_review(self):
        result = _classify(context_detail=_detail(url="https://gitlab.com/group/project/-/merge_requests/12"))

        assert result.category == SessionCategory.code_review

    def test_bitbucket_pull_requests_url_classifies_as_code_review(self):
        result = _classify(context_detail=_detail(url="https://bitbucket.org/team/repo/pull-requests/4"))

        assert result.category == SessionCategory.code_review

    def test_title_fallback_when_url_unavailable_eg_firefox(self):
        """A real GitHub PR tab's title never contains the URL text -- it reads like this. Without a
        title-shaped pattern, Firefox (which exposes no URL at all) could never classify Code Review."""
        result = _classify(
            window_title="Add title digest by toheed · Pull Request #58 · ToheedAsghar/Logline · GitHub",
            context_detail=None,
        )

        assert result.category == SessionCategory.code_review

    def test_gitlab_title_fallback(self):
        result = _classify(window_title="Add title digest (!12) · Merge request · group/project · GitLab")

        assert result.category == SessionCategory.code_review


class TestDocumentation:
    def test_google_docs_url_classifies_as_documentation(self):
        result = _classify(context_detail=_detail(url="https://docs.google.com/document/d/abc"))

        assert result.category == SessionCategory.documentation

    def test_notion_url_classifies_as_documentation(self):
        result = _classify(context_detail=_detail(url="https://www.notion.so/Some-Page-abc123"))

        assert result.category == SessionCategory.documentation

    def test_confluence_wiki_url_classifies_as_documentation(self):
        result = _classify(context_detail=_detail(url="https://mycompany.atlassian.net/wiki/spaces/ENG/page"))

        assert result.category == SessionCategory.documentation

    def test_google_docs_title_fallback_when_url_unavailable(self):
        result = _classify(window_title="Design proposal - Google Docs", context_detail=None)

        assert result.category == SessionCategory.documentation


class TestComms:
    def test_slack_url_classifies_as_comms(self):
        result = _classify(context_detail=_detail(url="https://app.slack.com/client/T1/C1"))

        assert result.category == SessionCategory.comms

    def test_whatsapp_url_classifies_as_comms(self):
        result = _classify(context_detail=_detail(url="https://web.whatsapp.com/"))

        assert result.category == SessionCategory.comms

    def test_native_whatsapp_app_with_no_url_classifies_as_comms_via_bundle_id(self):
        result = _classify(bundle_id=WHATSAPP_BUNDLE_ID, context_detail=None)

        assert result.category == SessionCategory.comms

    def test_native_slack_app_with_no_url_classifies_as_comms_via_bundle_id(self):
        result = _classify(bundle_id=SLACK_BUNDLE_ID, context_detail=None)

        assert result.category == SessionCategory.comms

    def test_slack_title_fallback_when_url_unavailable(self):
        result = _classify(window_title="general | Logline - Slack", context_detail=None)

        assert result.category == SessionCategory.comms


class TestCoding:
    def test_known_ide_with_project_path_classifies_as_coding(self):
        result = _classify(bundle_id=VSCODE_BUNDLE_ID, project_path="/Users/dev/projects/logline")

        assert result.category == SessionCategory.coding

    def test_known_terminal_with_project_path_classifies_as_coding(self):
        result = _classify(bundle_id=TERMINAL_BUNDLE_ID, project_path="/Users/dev/projects/logline")

        assert result.category == SessionCategory.coding

    def test_known_ide_with_no_project_path_still_classifies_as_coding(self):
        """Real IDE/terminal sessions frequently arrive with no project_path (a tracker-side gap, not
        evidence the work wasn't real) -- requiring one here would misclassify genuine coding time into
        the Admin catch-all, which is exactly what drove most of a real day's fragmentation."""
        result = _classify(bundle_id=VSCODE_BUNDLE_ID, project_path=None)

        assert result.category == SessionCategory.coding

    def test_terminal_title_is_irrelevant_to_classification_since_it_is_already_redacted(self):
        """Terminal titles are always None by the time they reach the backend (blanket-redacted client-side
        in the tracker), so classification for a terminal must work from project_path and bundle_id alone."""
        result = _classify(bundle_id=TERMINAL_BUNDLE_ID, window_title=None, project_path="/Users/dev/logline")

        assert result.category == SessionCategory.coding


class TestAdminFallback:
    def test_unknown_app_with_no_signal_falls_to_admin_not_dropped(self):
        result = _classify(bundle_id=UNKNOWN_BUNDLE_ID, window_title="Some Random Window", project_path=None)

        assert result.category == SessionCategory.admin

    def test_browser_with_an_unrecognized_domain_falls_to_admin(self):
        result = _classify(bundle_id=CHROME_BUNDLE_ID, context_detail=_detail(url="https://news.ycombinator.com/"))

        assert result.category == SessionCategory.admin


class TestMalformedContextDetail:
    def test_malformed_json_does_not_raise_and_falls_through_to_a_later_rule(self):
        result = _classify(bundle_id=VSCODE_BUNDLE_ID, project_path="/Users/dev/logline", context_detail="{not json")

        assert result.category == SessionCategory.coding

    def test_context_detail_that_is_a_json_list_not_an_object_is_treated_as_empty(self):
        result = _classify(bundle_id=VSCODE_BUNDLE_ID, project_path="/Users/dev/logline", context_detail="[1, 2]")

        assert result.category == SessionCategory.coding

    def test_none_context_detail_does_not_raise(self):
        result = _classify(bundle_id=UNKNOWN_BUNDLE_ID, context_detail=None)

        assert result.category == SessionCategory.admin
