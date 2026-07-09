import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Input } from "@/atoms";
import { useSession } from "@/context/SessionContext";
import { ApiError } from "@/repositories/api/client";
import { AuthFieldLabel, AuthShell } from "./AuthShell";

export default function Signup() {
  const { signup } = useSession();
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      // signup() (SessionContext) chains straight into login() with the same
      // credentials, so a successful signup lands the user in the app —
      // there's no separate "verify your email" step in the backend today.
      await signup(email, password, name || undefined);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create an account — try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthShell
      title="Create your account"
      subtitle="Turn your GitHub, calendar and chat signals into logs and standups."
    >
      <form onSubmit={handleSubmit}>
        <AuthFieldLabel>Name</AuthFieldLabel>
        <Input
          type="text"
          autoComplete="name"
          placeholder="Jane Doe"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <AuthFieldLabel>Work email</AuthFieldLabel>
        <Input
          type="email"
          autoComplete="email"
          placeholder="you@company.dev"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <AuthFieldLabel>Password</AuthFieldLabel>
        <Input
          type="password"
          autoComplete="new-password"
          placeholder="••••••••"
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
          workingLabel="Creating account…"
        >
          Create account
        </Button>
      </form>
      <p className="mt-[18px] text-center text-[13px] text-muted">
        Already have an account?{" "}
        <Link to="/login" className="font-semibold text-accent-dim hover:underline">
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
