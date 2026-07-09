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

  // Keep the api/client.ts module in sync even on first mount / hot reload,
  // not just on subsequent applyToken calls.
  useEffect(() => {
    setAuthToken(token);
  }, [token]);

  const logout = useCallback(() => {
    applyToken(null);
  }, [applyToken]);

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
    () => ({ token, user, isAuthenticated: token !== null, login, signup, logout }),
    [token, user, login, signup, logout],
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
