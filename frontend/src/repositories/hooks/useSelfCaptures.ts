import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createSelfCapture, type SelfCaptureInput } from "../api/selfCaptures";
import { TIMELINE_KEY } from "./useTimeline";

/**
 * A self-capture now writes a real Event row server-side (source=
 * "self_capture", confidence="proven" — see backend/app/api/self_captures.py),
 * so the timeline query is invalidated here rather than callers hiding the
 * filled gap client-side/session-only.
 */
export function useCreateSelfCapture() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: SelfCaptureInput) => createSelfCapture(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [TIMELINE_KEY] });
    },
  });
}
