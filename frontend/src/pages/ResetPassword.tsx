import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button, Input } from "@/atoms";
import { AUTH_STRINGS } from "@/constants";
import { resetPassword } from "@/repositories/api/auth";
import { ApiError } from "@/repositories/api/client";
import { AuthFieldLabel, AuthShell } from "./AuthShell";

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const navigate = useNavigate();

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!token) {
      setError(AUTH_STRINGS.TOKEN_MISSING_OR_INVALID);
      return;
    }

    if (password.length < 8 || password.length > 128) {
      setError(AUTH_STRINGS.PASSWORD_LENGTH_ERROR);
      return;
    }

    if (password !== confirmPassword) {
      setError(AUTH_STRINGS.PASSWORD_MISMATCH);
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await resetPassword({ token, new_password: password });
      setSuccessMessage(res.message || AUTH_STRINGS.RESET_PASSWORD_SUCCESS);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : AUTH_STRINGS.TOKEN_MISSING_OR_INVALID);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!token) {
    return (
      <AuthShell
        title={AUTH_STRINGS.RESET_PASSWORD_TITLE}
        subtitle={AUTH_STRINGS.RESET_PASSWORD_SUBTITLE}
        hideDivider
      >
        <div className="mt-4 flex flex-col gap-4">
          <p className="rounded-md border border-sidebar-border bg-surface p-3 font-mono text-[12px] text-danger">
            {AUTH_STRINGS.TOKEN_MISSING_OR_INVALID}
          </p>
          <Button type="button" variant="secondary" onClick={() => navigate("/forgot-password")} className="w-full">
            Request a new reset link
          </Button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={AUTH_STRINGS.RESET_PASSWORD_TITLE}
      subtitle={AUTH_STRINGS.RESET_PASSWORD_SUBTITLE}
      hideDivider
    >
      {successMessage ? (
        <div className="mt-4 flex flex-col gap-4">
          <p className="rounded-md border border-sidebar-border bg-surface p-3 font-mono text-[12px] text-accent">
            {successMessage}
          </p>
          <Button type="button" variant="primary" onClick={() => navigate("/login")} className="w-full">
            {AUTH_STRINGS.CONTINUE_TO_SIGN_IN}
          </Button>
        </div>
      ) : (
        <form onSubmit={handleSubmit}>
          <AuthFieldLabel>{AUTH_STRINGS.NEW_PASSWORD_LABEL}</AuthFieldLabel>
          <Input
            type="password"
            autoComplete="new-password"
            placeholder={AUTH_STRINGS.PASSWORD_PLACEHOLDER}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <AuthFieldLabel>{AUTH_STRINGS.CONFIRM_PASSWORD_LABEL}</AuthFieldLabel>
          <Input
            type="password"
            autoComplete="new-password"
            placeholder={AUTH_STRINGS.PASSWORD_PLACEHOLDER}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
          />
          {error && <p className="mt-2 font-mono text-[11px] text-danger">{error}</p>}
          <Button
            type="submit"
            variant="primary"
            className="mt-5 w-full"
            working={isSubmitting}
            workingLabel={AUTH_STRINGS.RESET_PASSWORD_WORKING}
          >
            {AUTH_STRINGS.RESET_PASSWORD_BTN}
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
