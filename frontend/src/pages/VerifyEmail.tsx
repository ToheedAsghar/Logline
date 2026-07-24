import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/atoms";
import { AUTH_STRINGS } from "@/constants/authMessages";
import { verifyEmail } from "@/repositories/api/auth";
import { ApiError } from "@/repositories/api/client";
import { AuthShell } from "./AuthShell";

export default function VerifyEmail() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const navigate = useNavigate();
  const calledRef = useRef(false);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setError(AUTH_STRINGS.TOKEN_MISSING_OR_INVALID);
      setIsLoading(false);
      return;
    }

    if (calledRef.current) return;
    calledRef.current = true;

    verifyEmail(token)
      .then((res) => {
        setSuccessMessage(res.message || AUTH_STRINGS.VERIFY_EMAIL_SUCCESS);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : AUTH_STRINGS.VERIFY_EMAIL_FAILED);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [token]);

  return (
    <AuthShell
      title={AUTH_STRINGS.VERIFY_EMAIL_TITLE}
      subtitle={AUTH_STRINGS.VERIFY_EMAIL_SUBTITLE}
      hideDivider
    >
      <div className="mt-4 flex flex-col gap-4">
        {isLoading ? (
          <p className="font-mono text-[13px] text-muted">Checking verification token…</p>
        ) : error ? (
          <>
            <p className="rounded-md border border-sidebar-border bg-surface p-3 font-mono text-[12px] text-danger">
              {error}
            </p>
            <Button type="button" variant="secondary" onClick={() => navigate("/login")} className="w-full">
              {AUTH_STRINGS.CONTINUE_TO_SIGN_IN}
            </Button>
          </>
        ) : (
          <>
            <p className="rounded-md border border-sidebar-border bg-surface p-3 font-mono text-[12px] text-accent">
              {successMessage}
            </p>
            <Button type="button" variant="primary" onClick={() => navigate("/login")} className="w-full">
              {AUTH_STRINGS.CONTINUE_TO_SIGN_IN}
            </Button>
          </>
        )}
      </div>
    </AuthShell>
  );
}
