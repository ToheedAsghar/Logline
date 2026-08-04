import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AUTH_STRINGS } from "@/constants/authMessages";
import { useSession } from "@/context/SessionContext";

export default function OAuthCallback() {
  const [searchParams] = useSearchParams();
  const { loginWithToken } = useSession();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = searchParams.get("token");
    if (token) {
      loginWithToken(token);
      navigate("/", { replace: true });
    } else {
      setError(AUTH_STRINGS.GOOGLE_SSO_FAILED);
    }
  }, [searchParams, loginWithToken, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg font-sans text-text">
      <div className="w-full max-w-sm p-6 text-center animate-ll-rise">
        {error ? (
          <>
            <p className="font-mono text-[13px] text-danger mb-4">{error}</p>
            <button
              onClick={() => navigate("/login")}
              className="text-[13.5px] font-medium text-accent-dim hover:underline"
            >
              {AUTH_STRINGS.CONTINUE_TO_SIGN_IN}
            </button>
          </>
        ) : (
          <div>
            <h1 className="m-0 text-xl font-semibold tracking-[-0.02em]">{AUTH_STRINGS.OAUTH_CALLBACK_TITLE}</h1>
            <p className="mt-2 text-[13.5px] text-muted">{AUTH_STRINGS.OAUTH_CALLBACK_SUBTITLE}</p>
          </div>
        )}
      </div>
    </div>
  );
}
