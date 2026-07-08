import { useMutation } from "@tanstack/react-query";
import { createSelfCapture, type SelfCaptureInput } from "../api/selfCaptures";

export function useCreateSelfCapture() {
  return useMutation({
    mutationFn: (data: SelfCaptureInput) => createSelfCapture(data),
  });
}
