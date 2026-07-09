import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useSession } from "@/context/SessionContext";

/** Redirects to /login, remembering where the user was headed so login can
 * send them back — SessionContext is the single source of truth for auth
 * state, this component only reacts to it. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useSession();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <>{children}</>;
}
