import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Button, Input } from "@/atoms";
import { AUTH_STRINGS } from "@/constants/authMessages";
import { forgotPassword } from "@/repositories/api/auth";
import { ApiError } from "@/repositories/api/client";
import { AuthFieldLabel, AuthShell } from "./AuthShell";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setIsSubmitting(true);

    try {
      const res = await forgotPassword({ email });
      setMessage(res.message || AUTH_STRINGS.FORGOT_PASSWORD_GENERIC_SUCCESS);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : AUTH_STRINGS.DEFAULT_LOGIN_ERROR);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthShell
      title={AUTH_STRINGS.FORGOT_PASSWORD_TITLE}
      subtitle={AUTH_STRINGS.FORGOT_PASSWORD_SUBTITLE}
      hideDivider
    >
      {message ? (
        <div className="mt-4 flex flex-col gap-4">
          <p className="rounded-md border border-sidebar-border bg-surface p-3 font-mono text-[12px] text-accent">
            {message}
          </p>
          <p className="text-center text-[13px] text-muted">
            <Link to="/login" className="font-semibold text-accent-dim hover:underline">
              {AUTH_STRINGS.CONTINUE_TO_SIGN_IN}
            </Link>
          </p>
        </div>
      ) : (
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
          {error && <p className="mt-2 font-mono text-[11px] text-danger">{error}</p>}
          <Button
            type="submit"
            variant="primary"
            className="mt-5 w-full"
            working={isSubmitting}
            workingLabel={AUTH_STRINGS.SEND_RESET_LINK_WORKING}
          >
            {AUTH_STRINGS.SEND_RESET_LINK_BTN}
          </Button>
          <p className="mt-[18px] text-center text-[13px] text-muted">
            Remembered your password?{" "}
            <Link to="/login" className="font-semibold text-accent-dim hover:underline">
              {AUTH_STRINGS.SIGN_IN_BTN}
            </Link>
          </p>
        </form>
      )}
    </AuthShell>
  );
}
