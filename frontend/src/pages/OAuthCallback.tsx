import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button, Loading } from "@/atoms";
import { AUTH_STRINGS } from "@/constants/authMessages";
import { useSession } from "@/context/SessionContext";
import { googleExchange } from "@/repositories/api/auth";
import { AuthShell } from "./AuthShell";

export default function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const { loginWithToken } = useSession();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(true);

  const hasExchangedRef = useRef(false);

  useEffect(() => {
    if (hasExchangedRef.current) return;

    let token = searchParams.get("token");
    let code = searchParams.get("code");

    if (!token && !code && window.location.hash) {
      const hash = window.location.hash.replace(/^#/, "");
      const hashParams = new URLSearchParams(hash);
      token = hashParams.get("token");
      code = hashParams.get("code");
    }

    if (token) {
      hasExchangedRef.current = true;
      loginWithToken(token);
      navigate("/", { replace: true });
    } else if (code) {
      hasExchangedRef.current = true;
      googleExchange(code)
        .then((res) => {
          loginWithToken(res.access_token);
          navigate("/", { replace: true });
        })
        .catch((err) => {
          const msg = err instanceof Error ? err.message : AUTH_STRINGS.GOOGLE_SSO_FAILED;
          setError(msg || AUTH_STRINGS.GOOGLE_SSO_FAILED);
          setIsProcessing(false);
        });
    } else {
      hasExchangedRef.current = true;
      queueMicrotask(() => {
        setError(AUTH_STRINGS.GOOGLE_SSO_FAILED);
        setIsProcessing(false);
      });
    }
  }, [searchParams, loginWithToken, navigate]);

  return (
    <AuthShell
      title={AUTH_STRINGS.OAUTH_CALLBACK_TITLE}
      subtitle={AUTH_STRINGS.OAUTH_CALLBACK_SUBTITLE}
      hideDivider
    >
      <div className="mt-4 flex flex-col gap-4">
        {isProcessing ? (
          <div className="flex flex-col items-center justify-center gap-3 py-6">
            <Loading size="md" />
            <p className="font-mono text-[12px] text-muted">Authenticating with Google…</p>
          </div>
        ) : error ? (
          <>
            <p className="rounded-md border border-danger/30 bg-danger-soft p-3 font-mono text-[12px] text-danger">
              {error}
            </p>
            <Button
              type="button"
              variant="primary"
              onClick={() => navigate("/login")}
              className="w-full"
            >
              {AUTH_STRINGS.CONTINUE_TO_SIGN_IN}
            </Button>
          </>
        ) : null}
      </div>
    </AuthShell>
  );
}
