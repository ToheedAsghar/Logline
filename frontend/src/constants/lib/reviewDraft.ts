export const REVIEW_DRAFT_TEXTS = {
  NO_UNTRACKED_TIME_TITLE: "No untracked time to allocate",
  NO_UNTRACKED_TIME_DETAIL: "This draft has no unaccounted tracker time available for a new block.",

  // Action fallback titles for generate/approve/discard failures.
  GENERATE_ACTION_LABEL: "Could not generate a draft",
  APPROVE_ACTION_LABEL: "Could not save the day",
  DISCARD_ACTION_LABEL: "Could not discard the draft",

  // Discard confirmation dialogs.
  DISCARD_DRAFT_TITLE: "Discard reconciliation draft",
  DISCARD_DRAFT_PROMPT:
    "Discard this reconciliation draft and any unsaved edits? These dates will become available to reconcile again.",
  DISCARD_DRAFT_CONFIRM_LABEL: "Discard draft",
  DISCARD_DRAFT_WORKING_LABEL: "Discarding…",
  UNSAVED_CHANGES_PROMPT: "You have unsaved draft changes. Discard them and continue?",

  // Tracker-time error surfaced when an edit would exceed measured time.
  TRACKED_TIME_ERROR_TITLE: "Not enough unassigned tracker time",
  TRACKED_TIME_ERROR_DETAIL: "Reduce another allocation first, or add genuinely untracked work as a manual block.",

  // describeApiError / describeUnprocessable messages.
  VERIFICATION_REJECTED_TITLE: "Draft rejected by the server's checks",
  VERIFICATION_REJECTED_DEFAULT_DETAIL:
    "The draft did not match the evidence it was generated from, so nothing was saved.",
  INVALID_REQUEST_DETAIL: "The server rejected this request as invalid.",
  FEATURE_UNAVAILABLE_TITLE: "This feature isn't available on the server",
  FEATURE_UNAVAILABLE_DETAIL:
    "The backend has no /reconciliation endpoint. It is probably running a build from before " +
    "reconciliation was added — restart it from the current branch and try again.",
  SESSION_EXPIRED_TITLE: "Your session has expired",
  SESSION_EXPIRED_DETAIL: "Sign in again to keep going. Nothing was saved.",
  DRAFT_CHANGED_TITLE: "Draft changed on the server",
  DRAFT_CHANGED_RELOAD_DETAIL: "Reload the selected dates before continuing.",
  DRAFT_CHANGED_OTHER_TAB_DETAIL:
    "Another tab changed this draft. Discard your local edits and reload the selected dates to continue.",
  SERVER_UNREACHABLE_TITLE: "Could not reach the server",
  SERVER_UNREACHABLE_DETAIL:
    "The request never completed. Check that the backend is running and reachable, then try again. " +
    "Nothing was saved.",
} as const;
