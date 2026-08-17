import { useEffect } from "react";
import { act, render, renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SessionProvider, useSession } from "../SessionContext";
import { TOKEN_STORAGE_KEY } from "@/constants/authMessages";
import { apiRequest } from "@/repositories/api/client";

// Doesn't need to be cryptographically valid -- decodeUserFromToken only
// needs three dot-separated segments with a base64url-JSON middle one.
function fakeToken(userId = 1): string {
  const payload = btoa(JSON.stringify({ sub: String(userId), exp: 9999999999 }));
  return `header.${payload}.signature`;
}

function mockResponse(status: number, body: unknown) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

/** Mimics any real query hook (e.g. `useTimeline`) that fires a request in
 * its own effect on mount -- the exact shape that raced ahead of
 * SessionContext's auth sync when that sync lived in a `useEffect` (React
 * commits effects child-first on mount, so this component's effect could
 * run before a parent-level sync effect). */
function FetchOnMount() {
  useEffect(() => {
    apiRequest("/timeline", { query: { start: "2026-01-01", end: "2026-01-02" } }).catch(() => {});
  }, []);
  return null;
}

describe("SessionContext auth hydration", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("attaches the Authorization header to a child's very first on-mount request when a valid token is already in localStorage", async () => {
    const token = fakeToken(42);
    localStorage.setItem(TOKEN_STORAGE_KEY, token);

    const fetchMock = vi.fn().mockResolvedValue(mockResponse(200, []));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <SessionProvider>
        <FetchOnMount />
      </SessionProvider>,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    // This is the crux of the regression: on a hard reload with an
    // already-valid stored token, SessionContext must have synced `client.ts`
    // before this child's mount-time request went out -- not one render/tick
    // later -- or the very first authenticated request silently drops the
    // Authorization header.
    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }];
    expect(requestInit.headers.Authorization).toBe(`Bearer ${token}`);
  });

  it("does not spuriously log out a valid session: a successful first request leaves the token in place", async () => {
    const token = fakeToken(7);
    localStorage.setItem(TOKEN_STORAGE_KEY, token);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockResponse(200, [])),
    );

    const { result } = renderHook(() => useSession(), {
      wrapper: ({ children }) => (
        <SessionProvider>
          <FetchOnMount />
          {children}
        </SessionProvider>
      ),
    });

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));
    // Give any stray microtask a chance to run before asserting the negative.
    await new Promise((r) => setTimeout(r, 0));
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe(token);
    expect(result.current.isAuthenticated).toBe(true);
  });

  it("still logs out (clears the stored token) when a request genuinely comes back 401", async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, "garbage.token.value");

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockResponse(401, { detail: "Unauthorized" })),
    );

    const { result } = renderHook(() => useSession(), {
      wrapper: ({ children }) => (
        <SessionProvider>
          <FetchOnMount />
          {children}
        </SessionProvider>
      ),
    });

    await waitFor(() => expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull());
    expect(result.current.isAuthenticated).toBe(false);
  });

  it("logoutAll resolves (not throws) and clears the session when both the access token and refresh cookie are already dead", async () => {
    // Reproduces the race an adversarial review found: /auth/logout-all 401s, client.ts's own 401-retry
    // machinery tries /auth/refresh (also 401, since the refresh cookie is dead too), gives up, and fires the
    // hidden unauthorizedHandler (logout()) BEFORE the 401 ever propagates back up to logoutAll's own catch.
    // logoutAll must treat that as success, not surface a spurious failure to the caller.
    localStorage.setItem(TOKEN_STORAGE_KEY, fakeToken(9));

    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/auth/logout-all")) return Promise.resolve(mockResponse(401, { detail: "Unauthorized" }));
      if (url.includes("/auth/refresh")) return Promise.resolve(mockResponse(401, { detail: "Invalid" }));
      return Promise.resolve(mockResponse(200, []));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useSession(), {
      wrapper: SessionProvider,
    });

    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    await expect(result.current.logoutAll()).resolves.toBeUndefined();

    await waitFor(() => expect(result.current.isAuthenticated).toBe(false));
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });
});

describe("SessionContext logout during an in-flight refresh", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("discards a refresh that resolves after logout instead of resurrecting the session", async () => {
    // logout() clears local state synchronously but cannot cancel a /auth/refresh request the browser has already
    // sent. Without a generation check in client.ts, that request's success path reinstates an access token into a
    // session the user just ended -- the tab silently logs itself back in. The refresh here is held open until
    // after logout has run, which is exactly the timing that reproduced it.
    localStorage.setItem(TOKEN_STORAGE_KEY, fakeToken(11));

    let landRefreshResponse!: () => void;
    const heldRefresh = new Promise((resolve) => {
      landRefreshResponse = () => resolve(mockResponse(200, { access_token: fakeToken(11) }));
    });

    // The data request 401s once (expired access token) and would succeed on the post-refresh retry. That second
    // half matters: if the retry also 401'd, client.ts would log out again on its own and hide the resurrection.
    let dataRequests = 0;
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/auth/refresh")) return heldRefresh;
      if (url.includes("/auth/logout")) return Promise.resolve(mockResponse(200, { message: "ok" }));
      dataRequests += 1;
      return Promise.resolve(
        dataRequests === 1 ? mockResponse(401, { detail: "Unauthorized" }) : mockResponse(200, []),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useSession(), { wrapper: SessionProvider });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    const pendingRequest = apiRequest("/entries").catch(() => {});
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/auth/refresh"))).toBe(true),
    );

    act(() => result.current.logout());
    expect(result.current.isAuthenticated).toBe(false);

    landRefreshResponse();
    await pendingRequest;

    await new Promise((r) => setTimeout(r, 0));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.token).toBeNull();
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it("keeps an in-flight refresh alive across a re-render that is not a logout", async () => {
    let landRefreshResponse!: () => void;
    const heldRefresh = new Promise((resolve) => {
      landRefreshResponse = () => resolve(mockResponse(200, { access_token: fakeToken(17) }));
    });

    let dataRequests = 0;
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/auth/refresh")) return heldRefresh;
      dataRequests += 1;
      return Promise.resolve(
        dataRequests === 1 ? mockResponse(401, { detail: "Unauthorized" }) : mockResponse(200, []),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderHook(() => useSession(), { wrapper: SessionProvider });

    const pendingRequest = apiRequest("/entries");
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/auth/refresh"))).toBe(true),
    );

    rerender();
    rerender();

    landRefreshResponse();
    await expect(pendingRequest).resolves.toEqual([]);
  });
});

describe("SessionContext benign concurrent refresh", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("does not log out when /auth/refresh reports a concurrent rotation (409)", async () => {
    const token = fakeToken(19);
    localStorage.setItem(TOKEN_STORAGE_KEY, token);

    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/auth/refresh")) {
        return Promise.resolve(mockResponse(409, { detail: "Refresh already completed by another request; retry" }));
      }
      return Promise.resolve(mockResponse(401, { detail: "Unauthorized" }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useSession(), { wrapper: SessionProvider });
    await waitFor(() => expect(result.current.isAuthenticated).toBe(true));

    await expect(apiRequest("/entries")).rejects.toThrow();

    expect(result.current.isAuthenticated).toBe(true);
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe(token);
  });
});
