import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, type Location } from "react-router-dom";
import { Button, Input } from "@/atoms";
import { useSession } from "@/context/SessionContext";
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

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't log in — try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthShell title="Sign in to Logline" subtitle="Pick up right where your timeline left off.">
      <form onSubmit={handleSubmit}>
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
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && <p className="mt-2 font-mono text-[11px] text-danger">{error}</p>}
        <Button type="submit" variant="primary" className="mt-5 w-full" working={isSubmitting} workingLabel="Logging in…">
          Sign in
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