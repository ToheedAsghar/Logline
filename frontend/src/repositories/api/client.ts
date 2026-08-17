/**
 * Thin fetch wrapper shared by every file in `repositories/api/`. Holds the
 * JWT, the 401 handler, and the access-token-refreshed handler as module
 * state (not React state) because these are plain functions, not hooks —
 * `SessionContext` is the only thing that calls `setAuthToken`/
 * `setUnauthorizedHandler`/`setAccessTokenRefreshedHandler`, wiring this
 * module up to React state without the reverse (`client.ts` never imports
 * React).
 *
 * The refresh token itself never passes through this module — it lives in an
 * httpOnly cookie the browser attaches automatically (`credentials:
 * "include"`) and this code can't read.
 */

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const REFRESH_PATH = "/auth/refresh";

let authToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;
let accessTokenRefreshedHandler: ((token: string) => void) | null = null;

/**
 * Bumped only by `endAuthSession`, never by `setAuthToken` itself — `setAuthToken(null)` also runs on every render
 * while logged out (see `SessionContext`'s render-body sync), and bumping there would discard an in-flight refresh
 * on any unrelated re-render, not just a real logout.
 *
 * `performRefresh` reads this before its fetch and re-checks it after, so a refresh that was already in flight when
 * the user logged out is discarded instead of reinstating a token — `logout()` clears local state synchronously but
 * cannot cancel a request the browser has already sent, and the server's refresh response can legitimately arrive
 * after the revoke.
 */
let authGeneration = 0;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

/** Call only from an actual session-end transition (`SessionContext.logout`/`logoutAll`), never from a plain
 * re-render — see the comment on `authGeneration` above. */
export function endAuthSession(): void {
  authGeneration += 1;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

/** Called whenever a 401 retry silently obtains a new access token, so `SessionContext` can persist it. */
export function setAccessTokenRefreshedHandler(handler: ((token: string) => void) | null): void {
  accessTokenRefreshedHandler = handler;
}

function formatErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (typeof d === "object" && d !== null && "msg" in d ? String(d.msg) : JSON.stringify(d))).join("; ");
  }
  if (typeof detail === "object" && detail !== null) {
    return JSON.stringify(detail);
  }
  return null;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    const detail = typeof body === "object" && body !== null && "detail" in body ? (body as { detail: unknown }).detail : null;
    super(formatErrorDetail(detail) ?? `Request failed with status ${status}`);
    this.name = "ApiError";
  }
}


interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | undefined>;
  /** Skip attaching the Authorization header — only auth/signup and auth/login need this. */
  skipAuth?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(path, BASE_URL);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

function rawFetch(path: string, method: string, body: unknown, query: RequestOptions["query"], skipAuth: boolean): Promise<Response> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!skipAuth && authToken) headers["Authorization"] = `Bearer ${authToken}`;

  return fetch(buildUrl(path, query), {
    method,
    headers,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

/**
 * `performRefresh`'s three possible outcomes:
 * - "refreshed": a new access token was obtained and applied.
 * - "retry": the server reported 409 (the presented refresh cookie was rotated away by a concurrent request, almost
 *   certainly another tab racing the same rotation, within the server's grace window) even after one immediate
 *   retry. The session is still good — the caller must not log out, just accept this request failing.
 * - "rejected": the refresh token is genuinely dead, or the session ended locally while the request was in flight.
 */
type RefreshOutcome = "refreshed" | "retry" | "rejected";

/**
 * Every concurrent 401 within the same tab awaits this same in-flight promise instead of each calling
 * `/auth/refresh` independently — without this, two requests that both expire around the same moment would race
 * two rotations of the same refresh-token cookie, and the loser would be wrongly logged out.
 */
let refreshPromise: Promise<RefreshOutcome> | null = null;

async function performRefresh(): Promise<RefreshOutcome> {
  const generation = authGeneration;
  try {
    let response = await fetch(buildUrl(REFRESH_PATH), { method: "POST", credentials: "include" });
    if (response.status === 409) {
      response = await fetch(buildUrl(REFRESH_PATH), { method: "POST", credentials: "include" });
    }
    if (response.status === 409) return "retry";
    if (!response.ok) return "rejected";
    const data = (await response.json()) as { access_token: string };
    if (generation !== authGeneration) return "rejected";
    authToken = data.access_token;
    accessTokenRefreshedHandler?.(data.access_token);
    return "refreshed";
  } catch {
    return "rejected";
  }
}

function refreshAccessToken(): Promise<RefreshOutcome> {
  if (refreshPromise === null) {
    refreshPromise = performRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function toResult<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new ApiError(response.status, await response.json().catch(() => null));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, skipAuth = false } = options;

  const response = await rawFetch(path, method, body, query, skipAuth);

  if (response.status === 401 && !skipAuth) {
    const outcome = await refreshAccessToken();
    if (outcome === "refreshed") {
      const retryResponse = await rawFetch(path, method, body, query, skipAuth);
      if (retryResponse.status !== 401) {
        return toResult<T>(retryResponse);
      }
    }
    if (outcome !== "retry") {
      unauthorizedHandler?.();
    }
    throw new ApiError(401, await response.json().catch(() => null));
  }

  return toResult<T>(response);
}
