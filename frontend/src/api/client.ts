import { getCookie } from "@/lib/utils";

export const CSRF_COOKIE = "crm_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export interface ApiErrorShape {
  code: string;
  message: string;
  details?: unknown;
}

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function parseApiError(status: number, body: unknown): ApiError {
  if (typeof body === "object" && body !== null && "error" in body) {
    const err = (body as { error: ApiErrorShape }).error;
    if (typeof err?.code === "string" && typeof err?.message === "string") {
      return new ApiError(status, err.code, err.message, err.details);
    }
  }
  return new ApiError(status, "UNKNOWN_ERROR", `Запрос завершился с ошибкой (${status})`);
}

export interface RequestOptions extends RequestInit {
  /** Skip the login redirect on 401 (used by the login/me probes themselves). */
  noAuthRedirect?: boolean;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { noAuthRedirect, ...init } = options;
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (UNSAFE_METHODS.has(method) && path !== "/api/auth/login") {
    const token = getCookie(CSRF_COOKIE);
    if (token) {
      headers.set(CSRF_HEADER, token);
    }
  }
  const response = await fetch(path, { ...init, headers, credentials: "include" });
  if (response.status === 401 && !noAuthRedirect) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    throw new ApiError(401, "UNAUTHORIZED", "Требуется вход");
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  const body: unknown = text ? (JSON.parse(text) as unknown) : null;
  if (!response.ok) {
    throw parseApiError(response.status, body);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => apiFetch<T>(path, options),
  post: <T>(path: string, data?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", body: JSON.stringify(data ?? {}) }),
  patch: <T>(path: string, data?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PATCH", body: JSON.stringify(data ?? {}) }),
  put: <T>(path: string, data?: unknown, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PUT", body: JSON.stringify(data ?? {}) }),
  del: <T>(path: string, options?: RequestOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};
