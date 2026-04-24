import { getApiBaseUrl, getApiHttpBaseUrl } from "@/lib/env";
import { clearAuthState, setAuthState } from "@/lib/auth-state";
import { readCookie, writeCookie, clearCookie } from "@/lib/cookie";
import ERROR_ZH from "@/messages/zh/error.json";
import ERROR_EN from "@/messages/en/error.json";

const WORKSPACE_COOKIE_NAME = "mingrun_workspace_id";
const LEGACY_WORKSPACE_COOKIE_NAME = "qihang_workspace_id";
export const AUTH_SESSION_EXPIRED_EVENT = "mingrun:auth-session-expired";

let cachedCsrfToken: string | null = null;
let authSessionRedirectScheduled = false;

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: Record<string, unknown>;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      details?: Record<string, unknown>;
    },
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;
  }
}

export function isApiRequestError(error: unknown): error is ApiRequestError {
  return error instanceof ApiRequestError;
}

function isEnglishLocale(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.location.pathname === "/en" || window.location.pathname.startsWith("/en/");
}

// Lib-level error messages read directly from messages/{zh,en}/error.json so
// that translations stay in one place, even though this module can't use
// next-intl hooks (it's callable from non-React code paths).
function readErrorMessage(key: "api.connection" | "api.csrfFailed"): string {
  const table = (isEnglishLocale() ? ERROR_EN : ERROR_ZH) as Record<string, string>;
  return table[key] ?? key;
}

function buildNetworkUnavailableMessage(apiBaseUrl: string): string {
  return readErrorMessage("api.connection").replace("{apiBaseUrl}", apiBaseUrl);
}

function toApiRequestError(error: unknown, apiBaseUrl: string): ApiRequestError {
  if (error instanceof ApiRequestError) {
    return error;
  }
  return new ApiRequestError(buildNetworkUnavailableMessage(apiBaseUrl), {
    status: 0,
    code: "network_unreachable",
    details: { apiBaseUrl },
  });
}


function readWorkspaceId(): string | null {
  return readCookie(WORKSPACE_COOKIE_NAME) || readCookie(LEGACY_WORKSPACE_COOKIE_NAME);
}

function clearCachedSecurityState(): void {
  cachedCsrfToken = null;
}

function dispatchAuthSessionExpired(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_EXPIRED_EVENT));
}

function isPublicMutation(path: string): boolean {
  return [
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/send-code",
    "/api/v1/auth/reset-password",
  ].includes(path);
}

async function ensureCsrfToken(options?: { suppressUnauthorizedHandling?: boolean }): Promise<string> {
  if (cachedCsrfToken) {
    return cachedCsrfToken;
  }
  const apiBaseUrl = getApiBaseUrl();
  const apiHttpBaseUrl = getApiHttpBaseUrl();
  let res: Response;
  try {
    res = await fetch(`${apiHttpBaseUrl}/api/v1/auth/csrf`, {
      credentials: "include",
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw toApiRequestError(error, apiBaseUrl);
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !options?.suppressUnauthorizedHandling) {
    handleUnauthorizedSession();
  }
  if (!res.ok || !data?.csrf_token) {
    throw new Error(data?.error?.message || readErrorMessage("api.csrfFailed"));
  }
  cachedCsrfToken = data.csrf_token as string;
  return cachedCsrfToken;
}

function getCurrentNextPath(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const { pathname, search, hash } = window.location;
  if (
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname === "/en/login" ||
    pathname.startsWith("/en/login/") ||
    pathname === "/register" ||
    pathname.startsWith("/register/") ||
    pathname === "/en/register" ||
    pathname.startsWith("/en/register/")
  ) {
    return null;
  }
  return `${pathname}${search}${hash}`;
}

function getLocaleAwareLoginPath(nextPath?: string | null): string {
  if (typeof window === "undefined") {
    return "/login";
  }
  const basePath =
    window.location.pathname === "/en" || window.location.pathname.startsWith("/en/")
      ? "/en/login"
      : "/login";
  if (!nextPath) {
    return basePath;
  }
  const params = new URLSearchParams();
  params.set("next", nextPath);
  return `${basePath}?${params.toString()}`;
}

function handleUnauthorizedSession(): void {
  clearCachedSecurityState();
  if (typeof window === "undefined") {
    clearAuthState();
    clearWorkspaceId();
    return;
  }

  dispatchAuthSessionExpired();
  if (authSessionRedirectScheduled) {
    return;
  }

  authSessionRedirectScheduled = true;
  const loginPath = getLocaleAwareLoginPath(getCurrentNextPath());

  window.setTimeout(() => {
    clearAuthState();
    clearWorkspaceId();
    authSessionRedirectScheduled = false;
    window.location.href = loginPath;
  }, 1200);
}

function buildHeaders(
  path: string,
  method: string,
  initialHeaders?: HeadersInit,
  contentType = "application/json",
  csrfToken?: string,
): Headers {
  const headers = new Headers(initialHeaders || {});
  if (contentType && !headers.has("Content-Type")) {
    headers.set("Content-Type", contentType);
  }
  const workspaceId = readWorkspaceId();
  if (workspaceId && !headers.has("X-Workspace-ID")) {
    headers.set("X-Workspace-ID", workspaceId);
  }
  if (csrfToken && !isPublicMutation(path) && ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase())) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  return headers;
}

async function parseResponse<T>(
  res: Response,
  options?: { suppressUnauthorizedHandling?: boolean },
): Promise<T> {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && !options?.suppressUnauthorizedHandling) {
      handleUnauthorizedSession();
    } else if (res.status === 403) {
      clearCachedSecurityState();
    } else if (res.status === 402) {
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("mrai:plan-required", { detail: data?.error || data }));
      }
      throw new ApiRequestError(data?.error?.message || data?.detail || "Plan upgrade required", {
        status: res.status,
        code: data?.error?.code,
        details: data?.error?.details,
      });
    }
    const errorMessage = data?.error?.message || `Request failed with status ${res.status}`;
    throw new ApiRequestError(errorMessage, {
      status: res.status,
      code: data?.error?.code,
      details: data?.error?.details,
    });
  }
  return data as T;
}

async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: { requireCsrf?: boolean; contentType?: string; suppressUnauthorizedHandling?: boolean } = {},
): Promise<T> {
  const apiBaseUrl = getApiBaseUrl();
  const apiHttpBaseUrl = getApiHttpBaseUrl();
  const method = (init.method || "GET").toUpperCase();
  const requireCsrf =
    options.requireCsrf ?? (!isPublicMutation(path) && ["POST", "PUT", "PATCH", "DELETE"].includes(method));
  const csrfToken = requireCsrf ? await ensureCsrfToken({ suppressUnauthorizedHandling: options.suppressUnauthorizedHandling }) : undefined;
  let res: Response;
  try {
    res = await fetch(`${apiHttpBaseUrl}${path}`, {
      ...init,
      credentials: "include",
      headers: buildHeaders(path, method, init.headers, options.contentType, csrfToken),
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw toApiRequestError(error, apiBaseUrl);
  }
  return parseResponse<T>(res, {
    suppressUnauthorizedHandling: options.suppressUnauthorizedHandling ?? isPublicMutation(path),
  });
}

/**
 * Build authenticated headers for a streaming POST request.
 * Acquires CSRF token and workspace ID, matching the same logic used by apiPost.
 */
export async function buildStreamPostHeaders(path: string): Promise<Headers> {
  const csrfToken = !isPublicMutation(path) ? await ensureCsrfToken() : undefined;
  return buildHeaders(path, "POST", undefined, "application/json", csrfToken);
}

/**
 * Handle a 401 response received during a streaming request.
 */
export function handleStreamUnauthorized(): void {
  handleUnauthorizedSession();
}

export async function apiGet<T>(
  path: string,
  init?: RequestInit,
  options: { suppressUnauthorizedHandling?: boolean } = {},
): Promise<T> {
  return apiRequest<T>(path, init, {
    requireCsrf: false,
    suppressUnauthorizedHandling: options.suppressUnauthorizedHandling,
  });
}

export async function apiPost<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return apiRequest<T>(
    path,
    {
      method: "POST",
      ...init,
      body: body ? JSON.stringify(body) : undefined,
    },
    { requireCsrf: !isPublicMutation(path) },
  );
}

export async function apiPatch<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return apiRequest<T>(
    path,
    {
      method: "PATCH",
      ...init,
      body: body ? JSON.stringify(body) : undefined,
    },
    { requireCsrf: true },
  );
}

export async function apiDelete<T>(path: string): Promise<T> {
  return apiRequest<T>(
    path,
    {
      method: "DELETE",
    },
    { requireCsrf: true },
  );
}

export async function uploadToPresignedUrl(
  path: string,
  init: RequestInit,
  options: { authenticated?: boolean } = {},
): Promise<Response> {
  const { authenticated = false } = options;
  const apiBaseUrl = getApiBaseUrl();
  const method = (init.method || "PUT").toUpperCase();
  const isApiUrl = path.startsWith(apiBaseUrl);
  const headers = new Headers(init.headers || {});
  if (authenticated && isApiUrl) {
    const csrfToken = await ensureCsrfToken();
    const workspaceId = readWorkspaceId();
    headers.set("X-CSRF-Token", csrfToken);
    if (workspaceId) {
      headers.set("X-Workspace-ID", workspaceId);
    }
  }
  return fetch(path, {
    ...init,
    method,
    credentials: isApiUrl ? "include" : init.credentials,
    headers,
  });
}

export function buildPresignedUploadInit(
  presign: {
    upload_method?: "PUT" | "POST";
    headers: Record<string, string>;
    fields?: Record<string, string>;
  },
  file: Blob,
): RequestInit {
  if (presign.upload_method === "POST") {
    const formData = new FormData();
    for (const [key, value] of Object.entries(presign.fields || {})) {
      formData.append(key, value);
    }
    formData.append("file", file);
    return {
      method: "POST",
      body: formData,
    };
  }

  return {
    method: "PUT",
    headers: presign.headers,
    body: file,
  };
}

export function persistWorkspaceId(workspaceId: string, authStateMaxAgeSeconds?: number): void {
  writeCookie(WORKSPACE_COOKIE_NAME, workspaceId);
  clearCookie(LEGACY_WORKSPACE_COOKIE_NAME);
  setAuthState(authStateMaxAgeSeconds);
}

export function clearWorkspaceId(): void {
  clearCookie(WORKSPACE_COOKIE_NAME);
  clearCookie(LEGACY_WORKSPACE_COOKIE_NAME);
}

export async function logout(): Promise<boolean> {
  // Treat the server-side logout as best-effort. Whether it succeeds or fails,
  // we must clear local auth state and redirect — otherwise the user clicks
  // "Sign out" and sees nothing happen when the network is flaky.
  let serverOk = true;
  try {
    await apiRequest<void>(
      "/api/v1/auth/logout",
      { method: "POST" },
      { requireCsrf: true, suppressUnauthorizedHandling: true },
    );
  } catch {
    serverOk = false;
  }
  clearAuthState();
  clearWorkspaceId();
  clearCachedSecurityState();
  window.location.href = getLocaleAwareLoginPath();
  return serverOk;
}

export async function apiPostFormData<T>(path: string, formData: FormData, init?: RequestInit): Promise<T> {
  return apiRequest<T>(
    path,
    {
      method: "POST",
      ...init,
      body: formData,
    },
    { requireCsrf: !isPublicMutation(path), contentType: "" },
  );
}

export async function apiPut<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return apiRequest<T>(
    path,
    {
      method: "PUT",
      ...init,
      body: body ? JSON.stringify(body) : undefined,
    },
    { requireCsrf: !isPublicMutation(path) },
  );
}
