import { useEffect } from "react";
import { render, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SessionProvider, useSession } from "../SessionContext";
import { apiRequest } from "@/repositories/api/client";

const TOKEN_STORAGE_KEY = "logline_token";

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

    let session: ReturnType<typeof useSession> | undefined;
    function Probe() {
      session = useSession();
      return <FetchOnMount />;
    }

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    await waitFor(() => expect(session?.isAuthenticated).toBe(true));
    // Give any stray microtask a chance to run before asserting the negative.
    await new Promise((r) => setTimeout(r, 0));
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe(token);
    expect(session?.isAuthenticated).toBe(true);
  });

  it("still logs out (clears the stored token) when a request genuinely comes back 401", async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, "garbage.token.value");

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockResponse(401, { detail: "Unauthorized" })),
    );

    let session: ReturnType<typeof useSession> | undefined;
    function Probe() {
      session = useSession();
      return <FetchOnMount />;
    }

    render(
      <SessionProvider>
        <Probe />
      </SessionProvider>,
    );

    await waitFor(() => expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull());
    expect(session?.isAuthenticated).toBe(false);
  });
});
