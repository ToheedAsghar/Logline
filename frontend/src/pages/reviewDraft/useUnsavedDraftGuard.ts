import { useEffect } from "react";

import { REVIEW_DRAFT_TEXTS } from "@/constants";

export function useUnsavedDraftGuard(isDirty: boolean) {
  useEffect(() => {
    if (!isDirty) return;

    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const guardInternalLink = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(target instanceof HTMLAnchorElement) || target.target === "_blank") return;
      if (target.origin !== window.location.origin) return;
      if (window.confirm(REVIEW_DRAFT_TEXTS.UNSAVED_CHANGES_PROMPT)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
    };

    window.addEventListener("beforeunload", warnBeforeUnload);
    document.addEventListener("click", guardInternalLink, true);
    return () => {
      window.removeEventListener("beforeunload", warnBeforeUnload);
      document.removeEventListener("click", guardInternalLink, true);
    };
  }, [isDirty]);

  return () => !isDirty || window.confirm(REVIEW_DRAFT_TEXTS.UNSAVED_CHANGES_PROMPT);
}
