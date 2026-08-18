import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, type Location } from "react-router-dom";
import { Button, Input } from "@/atoms";
import { AUTH_STRINGS } from "@/constants";
import { useSession } from "@/context/SessionContext";
import { resendVerification } from "@/repositories/api/auth";
import { ApiError } from "@/repositories/api/client";
import { AuthFieldLabel, AuthShell } from "./AuthShell";

export default function Login() {
  const { login } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: Location } | null)?.from?.pathname ?? "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isUnverified, setIsUnverified] = useState(false);
  const [resendStatus, setResendStatus] = useState<string | null>(null);
  const [isResending, setIsResending] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsUnverified(false);
    setResendStatus(null);
    setIsSubmitting(true);

    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        if (err.status === 403) {
          setIsUnverified(true);
        }
      } else {
        setError(AUTH_STRINGS.DEFAULT_LOGIN_ERROR);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResendVerification = async () => {
    if (!email) return;
    setIsResending(true);
    try {
      const res = await resendVerification({ email });
      setResendStatus(res.message || AUTH_STRINGS.RESEND_VERIFICATION_SENT);
    } catch (err) {
      setResendStatus(err instanceof ApiError ? err.message : AUTH_STRINGS.DEFAULT_LOGIN_ERROR);
    } finally {
      setIsResending(false);
    }
  };

  return (
    <AuthShell title={AUTH_STRINGS.SIGN_IN_TITLE} subtitle={AUTH_STRINGS.SIGN_IN_SUBTITLE}>
      <form onSubmit={handleSubmit}>
        <AuthFieldLabel>{AUTH_STRINGS.WORK_EMAIL_LABEL}</AuthFieldLabel>
        <Input
          type="email"
          autoComplete="email"
          placeholder={AUTH_STRINGS.EMAIL_PLACEHOLDER}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <div className="flex items-center justify-between mt-[13px] mb-1.5">
          <label className="block font-mono text-[10.5px] tracking-[0.06em] text-faint uppercase">
            {AUTH_STRINGS.PASSWORD_LABEL}
          </label>
          <Link to="/forgot-password" className="text-[11.5px] font-medium text-accent-dim hover:underline">
            Forgot password?
          </Link>
        </div>
        <Input
          type="password"
          autoComplete="current-password"
          placeholder={AUTH_STRINGS.PASSWORD_PLACEHOLDER}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && <p className="mt-2 font-mono text-[11px] text-danger">{error}</p>}
        {isUnverified && (
          <div className="mt-3 flex flex-col gap-2">
            <Button
              type="button"
              variant="secondary"
              className="w-full text-xs"
              onClick={handleResendVerification}
              working={isResending}
              workingLabel={AUTH_STRINGS.RESEND_VERIFICATION_WORKING}
            >
              {AUTH_STRINGS.RESEND_VERIFICATION_BTN}
            </Button>
            {resendStatus && <p className="font-mono text-[11px] text-accent">{resendStatus}</p>}
          </div>
        )}
        <Button
          type="submit"
          variant="primary"
          className="mt-5 w-full"
          working={isSubmitting}
          workingLabel={AUTH_STRINGS.SIGN_IN_WORKING}
        >
          {AUTH_STRINGS.SIGN_IN_BTN}
        </Button>
      </form>
      <p className="mt-[18px] text-center text-[13px] text-muted">
        New to Logline?{" "}
        <Link to="/signup" className="font-semibold text-accent-dim hover:underline">
          Create one
        </Link>
      </p>
    </AuthShell>
  );
}
