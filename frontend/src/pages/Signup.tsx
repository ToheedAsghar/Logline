import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Input } from "@/atoms";
import { AUTH_STRINGS } from "@/constants/authMessages";
import { signup as signupApi } from "@/repositories/api/auth";
import { ApiError } from "@/repositories/api/client";
import { AuthFieldLabel, AuthShell } from "./AuthShell";

export default function Signup() {
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password.length < 8 || password.length > 128) {
      setError(AUTH_STRINGS.PASSWORD_LENGTH_ERROR);
      return;
    }

    setIsSubmitting(true);
    try {
      await signupApi({ email, password, name: name || undefined });
      setIsSuccess(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : AUTH_STRINGS.DEFAULT_SIGNUP_ERROR);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthShell
      title={AUTH_STRINGS.SIGN_UP_TITLE}
      subtitle={AUTH_STRINGS.SIGN_UP_SUBTITLE}
    >
      {isSuccess ? (
        <div className="mt-4 flex flex-col gap-4">
          <p className="rounded-md border border-sidebar-border bg-surface p-3 font-mono text-[12px] text-accent">
            {AUTH_STRINGS.SIGNUP_SUCCESS_VERIFY_PROMPT}
          </p>
          <Button type="button" variant="primary" onClick={() => navigate("/login")} className="w-full">
            {AUTH_STRINGS.CONTINUE_TO_SIGN_IN}
          </Button>
        </div>
      ) : (
        <form onSubmit={handleSubmit}>
          <AuthFieldLabel>{AUTH_STRINGS.NAME_LABEL}</AuthFieldLabel>
          <Input
            type="text"
            autoComplete="name"
            placeholder={AUTH_STRINGS.NAME_PLACEHOLDER}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <AuthFieldLabel>{AUTH_STRINGS.WORK_EMAIL_LABEL}</AuthFieldLabel>
          <Input
            type="email"
            autoComplete="email"
            placeholder={AUTH_STRINGS.EMAIL_PLACEHOLDER}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <AuthFieldLabel>{AUTH_STRINGS.PASSWORD_LABEL}</AuthFieldLabel>
          <Input
            type="password"
            autoComplete="new-password"
            placeholder={AUTH_STRINGS.PASSWORD_PLACEHOLDER}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <p className="mt-2 font-mono text-[11px] text-danger">{error}</p>}
          <Button
            type="submit"
            variant="primary"
            className="mt-5 w-full"
            working={isSubmitting}
            workingLabel={AUTH_STRINGS.CREATE_ACCOUNT_WORKING}
          >
            {AUTH_STRINGS.CREATE_ACCOUNT_BTN}
          </Button>
        </form>
      )}
      <p className="mt-[18px] text-center text-[13px] text-muted">
        Already have an account?{" "}
        <Link to="/login" className="font-semibold text-accent-dim hover:underline">
          {AUTH_STRINGS.SIGN_IN_BTN}
        </Link>
      </p>
    </AuthShell>
  );
}
