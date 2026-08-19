// Minimal typed fetch wrapper for the DockIQ API.
//
// - `API_BASE` covers everything under /api/v1 (hosts, containers, metrics,
//   alerts, ...).
// - `ORIGIN_BASE` is used for the root-level health probes (/healthz, /readyz)
//   which live outside the /api/v1 prefix.

export const API_BASE: string = import.meta.env.VITE_API_BASE || "/api/v1";
export const ORIGIN_BASE: string = "";

const TOKEN_KEY = "dockiq_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // ignore storage failures (e.g. private browsing)
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

// Called whenever a request comes back 401, so the auth context can drop the
// stale user/token state without every page needing to know about it.
let unauthorizedHandler: (() => void) | null = null;
export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Default request timeout. Individual calls (e.g. long-running diagnostics
// queries) may override via `timeoutMs`.
const DEFAULT_TIMEOUT_MS = 20000;

async function request<T>(url: string, init?: RequestInit, timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<T> {
  let res: Response;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const token = getToken();
  try {
    res = await fetch(url, {
      headers: {
        Accept: "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
      ...init,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(`Request to ${url} timed out after ${timeoutMs}ms`, 0);
    }
    throw new ApiError(
      `Network error contacting ${url}: ${err instanceof Error ? err.message : String(err)}`,
      0,
    );
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.clone().json();
      detail = body?.error?.detail || body?.error?.title || body?.detail || detail;
    } catch {
      // body wasn't JSON, fall back to statusText
    }
    if (res.status === 401) {
      clearToken();
      unauthorizedHandler?.();
    }
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function buildQuery(params?: Record<string, string | number | undefined>): string {
  if (!params) return "";
  const usable = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (usable.length === 0) return "";
  const search = new URLSearchParams(usable.map(([k, v]) => [k, String(v)]));
  return `?${search.toString()}`;
}

export function apiGet<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  timeoutMs?: number,
): Promise<T> {
  return request<T>(`${API_BASE}${path}${buildQuery(params)}`, undefined, timeoutMs);
}

export function apiPost<T>(path: string, body?: unknown, timeoutMs?: number): Promise<T> {
  return request<T>(
    `${API_BASE}${path}`,
    {
      method: "POST",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    timeoutMs,
  );
}

export function apiPut<T>(path: string, body?: unknown, timeoutMs?: number): Promise<T> {
  return request<T>(
    `${API_BASE}${path}`,
    {
      method: "PUT",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    timeoutMs,
  );
}

export function originGet<T>(path: string): Promise<T> {
  return request<T>(`${ORIGIN_BASE}${path}`);
}
