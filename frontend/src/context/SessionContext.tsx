import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { login as loginRequest, signup as signupRequest } from "@/repositories/api/auth";
import { setAuthToken, setUnauthorizedHandler } from "@/repositories/api/client";

const TOKEN_STORAGE_KEY = "logline_token";

interface SessionUser {
  id: number;
}

interface SessionContextValue {
  token: string | null;
  user: SessionUser | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithToken: (token: string) => void;
  signup: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
}

const SessionContext = createContext<SessionContextValue | undefined>(undefined);

// The JWT only encodes `{sub: "<user_id>", exp}` (see backend/app/core/security.py) --
// there's no `/auth/me` endpoint, so the id is read straight out of the token's
// payload rather than fetched. This is not signature-verified; that's fine here,
// since it's only ever used to label the locally-held token, never to authorize
// anything -- the backend re-verifies the token on every request.
function decodeUserFromToken(token: string): SessionUser | null {
  try {
    const payload = token.split(".")[1];
    const decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return { id: Number(decoded.sub) };
  } catch {
    return null;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_STORAGE_KEY));

  const applyToken = useCallback((next: string | null) => {
    setToken(next);
    if (next) {
      localStorage.setItem(TOKEN_STORAGE_KEY, next);
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
    setAuthToken(next);
  }, []);

  const logout = useCallback(() => {
    applyToken(null);
  }, [applyToken]);

  const loginWithToken = useCallback(
    (token: string) => {
      applyToken(token);
    },
    [applyToken],
  );

  // `client.ts` holds `authToken`/the 401 handler as plain module state (not
  // React state), which is exactly why syncing them from a `useEffect` is
  // unsafe: React commits effects child-first on mount, so a child that
  // fires a query on mount (e.g. `useTimeline`) can run *before* an effect
  // declared here. With a valid token already in `localStorage`, the
  // `useState` initializer above makes `isAuthenticated` true from this
  // component's very first render, so `RequireAuth` lets authenticated
  // children through immediately -- if the module sync only happened in an
  // effect, that child's first request went out with no `Authorization`
  // header, got a 401, and `logout()` wiped an otherwise-valid session
  // (reproduced by reloading with a valid stored token and watching the
  // first /timeline request race the sync). Calling these plain functions
  // directly in the render body -- not in an effect -- guarantees they're
  // correct before any child even starts rendering, closing the race
  // entirely rather than just narrowing it.
  setAuthToken(token);
  setUnauthorizedHandler(logout);

  // Also register/cleanup through a real effect (not just the synchronous
  // calls above). Reason: React 18 StrictMode's dev-only mount -> cleanup ->
  // mount dance double-invokes effects, and a *cleanup-only* effect (no-op
  // setup) would run: no-op setup, then this cleanup (nulling the handler),
  // then the no-op setup again -- leaving the handler stuck at `null` for
  // the rest of the component's life, with nothing left to restore it. Since
  // this effect's setup re-registers `logout`, the dance instead ends on
  // "logout registered", exactly like a single real mount would, while still
  // correctly clearing it on a genuine unmount.
  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  const login = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await loginRequest({ email, password });
      applyToken(access_token);
    },
    [applyToken],
  );

  const signup = useCallback(
    async (email: string, password: string, name?: string) => {
      await signupRequest({ email, password, name });
      await login(email, password);
    },
    [login],
  );

  const user = useMemo(() => (token ? decodeUserFromToken(token) : null), [token]);

  const value = useMemo<SessionContextValue>(
    () => ({ token, user, isAuthenticated: token !== null, login, loginWithToken, signup, logout }),
    [token, user, login, loginWithToken, signup, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return context;
}
