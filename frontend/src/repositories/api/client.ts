/**
 * Thin fetch wrapper shared by every file in `repositories/api/`. Holds the
 * JWT and the 401 handler as module state (not React state) because these
 * are plain functions, not hooks — `SessionContext` is the only thing that
 * calls `setAuthToken`/`setUnauthorizedHandler`, wiring this module up to
 * React state without the reverse (`client.ts` never imports React).
 */

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

let authToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(
      (typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : null) ?? `Request failed with status ${status}`,
    );
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

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, skipAuth = false } = options;

  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!skipAuth && authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const response = await fetch(buildUrl(path, query), {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (response.status === 401) {
    unauthorizedHandler?.();
    throw new ApiError(401, await response.json().catch(() => null));
  }

  if (!response.ok) {
    throw new ApiError(response.status, await response.json().catch(() => null));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
