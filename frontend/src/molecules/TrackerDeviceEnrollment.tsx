import { useState } from "react";
import { Button } from "@/atoms";
import { useEnrollTrackerDevice } from "@/repositories/hooks";

interface TrackerDeviceEnrollmentProps {
  deviceCount?: number;
}

export function TrackerDeviceEnrollment({ deviceCount = 0 }: TrackerDeviceEnrollmentProps) {
  const enrollMutation = useEnrollTrackerDevice();
  const [enrolledToken, setEnrolledToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buttonLabel = deviceCount > 0 ? "Connect another device" : "Connect this device";

  const handleEnroll = () => {
    setError(null);
    setCopied(false);
    enrollMutation.mutate(undefined, {
      onSuccess: (data) => {
        setEnrolledToken(data.token);
      },
      onError: (err) => {
        const message = err instanceof Error ? err.message : "Failed to generate tracker token.";
        setError(message || "Failed to generate tracker token. Please try again.");
      },
    });
  };

  const handleCopy = async () => {
    if (!enrolledToken) return;
    try {
      await navigator.clipboard.writeText(enrolledToken);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback if clipboard API is unavailable
      setCopied(false);
    }
  };

  const handleDone = () => {
    setEnrolledToken(null);
    setCopied(false);
  };

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div
          role="alert"
          aria-live="polite"
          className="flex items-center justify-between rounded-md border border-danger/40 bg-danger-soft px-3 py-2 font-mono text-xs text-danger"
        >
          <span>{error}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError(null)}
            className="ml-3 font-sans text-xs opacity-70 hover:opacity-100 focus:outline-none"
          >
            ✕
          </button>
        </div>
      )}

      {enrolledToken ? (
        <div
          role="region"
          aria-label="Device token"
          className="flex flex-col gap-2.5 rounded-lg border border-accent-soft bg-surface-2 p-3.5"
        >
          <div className="flex flex-col gap-0.5">
            <span className="text-xs font-semibold text-text">Device enrolled successfully</span>
            <p className="text-xs text-muted">
              Copy this token now. For security, it cannot be displayed again.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <code
              data-testid="device-token-display"
              className="flex-1 rounded border border-border-2 bg-surface px-3 py-1.5 font-mono text-xs text-text select-all overflow-x-auto"
            >
              {enrolledToken}
            </code>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={handleCopy}
            >
              {copied ? "Copied!" : "Copy token"}
            </Button>
          </div>

          <div className="flex justify-end pt-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleDone}
            >
              Done
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            working={enrollMutation.isPending}
            workingLabel="Generating token…"
            onClick={handleEnroll}
          >
            {buttonLabel}
          </Button>
        </div>
      )}
    </div>
  );
}
