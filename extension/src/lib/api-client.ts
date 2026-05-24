/**
 * Fetch wrapper used by the service worker to talk to
 * `/api/extension/*` (F8 / design §4.10).
 *
 * Responsibilities:
 *  - Attach `Authorization: Bearer <refresh_token>` for protected
 *    endpoints, reading the token from `chrome.storage.local` on every
 *    call (so a token refresh propagates immediately).
 *  - Retry with exponential backoff (0/1s/3s/9s) on 5xx and on network
 *    errors. 4xx is *not* retried.
 *  - Map well-known status codes to typed errors so the service worker
 *    can react (re-pair on 401, surface "outdated" UI on 409, throttle
 *    on 429).
 *
 * Backend base URL is resolved in this order:
 *  1. `import.meta.env.VITE_BACKEND_URL` — Vite build-time substitution.
 *     Set this in `extension/.env` (`VITE_BACKEND_URL=https://medzee-spy-production.up.railway.app`)
 *     so different builds (dev/staging/prod) target the right backend.
 *  2. `http://localhost:8000` — fallback for unconfigured local dev builds.
 *
 * The value is baked at build time — `npm run build` reads `.env`, swaps
 * the literal, and ships it. There's no runtime override hook (yet).
 */
import type {
  ExtensionMessageBatch,
  ExtensionPairRequest,
  ExtensionPairResponse,
  ExtensionStatusResponse,
  ExtensionTelemetryEventPayload,
} from "./messages.js";
import { getState } from "./storage.js";

const DEFAULT_BACKEND =
  (import.meta as ImportMeta & { env?: Record<string, string | undefined> })
    .env?.VITE_BACKEND_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";

// ─── Typed error classes (caught by service-worker switch) ─────────────

/** 401 from a protected endpoint — refresh_token is invalid or expired. */
export class PairingExpiredError extends Error {
  readonly code = "pairing_expired";

  constructor(message = "pairing expired") {
    super(message);
    this.name = "PairingExpiredError";
  }
}

/** 409 — backend rejected the request because `X-Extension-Version` is below floor. */
export class ExtensionOutdatedError extends Error {
  readonly code = "extension_outdated";
  readonly min_version: string | undefined;

  constructor(message: string, min_version?: string) {
    super(message);
    this.name = "ExtensionOutdatedError";
    this.min_version = min_version;
  }
}

/** 429 — backend rate-limited us (60 events/min/user on telemetry, etc). */
export class RateLimitedError extends Error {
  readonly code = "rate_limited";

  constructor(message = "rate limited") {
    super(message);
    this.name = "RateLimitedError";
  }
}

// ─── Internal fetch with retry ─────────────────────────────────────────

interface FetchOpts {
  method?: "GET" | "POST";
  body?: unknown;
  headers?: Record<string, string>;
  /** Attach `Authorization: Bearer <refresh_token>` from storage. */
  auth?: boolean;
  /** Sent as `X-Extension-Version` (CHX-14 floor check). */
  extensionVersion?: string;
}

/** Pluggable for tests — defaults to `http://localhost:8000`. */
async function backendBase(): Promise<string> {
  return DEFAULT_BACKEND;
}

/** Schedule: t=0, +1s, +3s, +9s → 4 total attempts. */
const RETRY_DELAYS_MS = [0, 1000, 3000, 9000] as const;

async function fetchJson<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const base = await backendBase();
  const url = base + path;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...opts.headers,
  };

  if (opts.extensionVersion) {
    headers["X-Extension-Version"] = opts.extensionVersion;
  }

  if (opts.auth) {
    const state = await getState();
    if (!state.refresh_token) {
      throw new PairingExpiredError("no refresh_token in storage");
    }
    headers["Authorization"] = `Bearer ${state.refresh_token}`;
  }

  const init: RequestInit = {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  };

  let lastError: unknown = null;
  for (const delay of RETRY_DELAYS_MS) {
    if (delay > 0) {
      await new Promise((r) => setTimeout(r, delay));
    }

    try {
      const res = await fetch(url, init);

      // Terminal status codes — surface as typed errors, never retry.
      if (res.status === 401) {
        throw new PairingExpiredError("401 from backend");
      }
      if (res.status === 409) {
        const body = await res.json().catch(() => ({}) as unknown);
        const detail = extractDetail(body);
        throw new ExtensionOutdatedError(
          detail.message ?? "extension outdated",
          detail.min_version,
        );
      }
      if (res.status === 429) {
        throw new RateLimitedError("429 from backend");
      }

      // 5xx → retry until budget exhausted.
      if (res.status >= 500) {
        lastError = new Error(`backend ${res.status}`);
        continue;
      }

      // Other 4xx → fail fast.
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
      }

      if (res.status === 204) {
        return undefined as T;
      }
      return (await res.json()) as T;
    } catch (e) {
      // Don't swallow typed errors — caller needs to react.
      if (
        e instanceof PairingExpiredError ||
        e instanceof ExtensionOutdatedError ||
        e instanceof RateLimitedError
      ) {
        throw e;
      }
      lastError = e;
      // Continue → try next backoff slot.
    }
  }

  throw lastError ?? new Error("unknown fetch failure");
}

/** Pull `{ detail: { message, min_version } }` out of a FastAPI error body. */
function extractDetail(body: unknown): { message?: string; min_version?: string } {
  if (typeof body !== "object" || body === null) return {};
  const root = body as Record<string, unknown>;
  const detail =
    typeof root.detail === "object" && root.detail !== null
      ? (root.detail as Record<string, unknown>)
      : root;
  return {
    message: typeof detail.message === "string" ? detail.message : undefined,
    min_version:
      typeof detail.min_version === "string" ? detail.min_version : undefined,
  };
}

// ─── Public API (one helper per endpoint) ──────────────────────────────

/** `POST /api/extension/pair` — no auth, returns the long-lived refresh token. */
export async function pair(
  req: ExtensionPairRequest,
): Promise<ExtensionPairResponse> {
  return fetchJson<ExtensionPairResponse>("/api/extension/pair", {
    method: "POST",
    body: req,
  });
}

/** `POST /api/extension/messages` — auth: refresh_token, 202 Accepted on success. */
export async function sendBatch(
  batch: ExtensionMessageBatch,
  extensionVersion: string,
): Promise<{ received: number; deduped?: number; total_received?: number }> {
  return fetchJson("/api/extension/messages", {
    method: "POST",
    body: batch,
    auth: true,
    extensionVersion,
  });
}

/**
 * `POST /api/extension/telemetry` — auth: refresh_token, rate-limited 60/min.
 * Returns `void`; the backend response is fire-and-forget for the worker.
 */
export async function sendTelemetry(
  event: ExtensionTelemetryEventPayload,
  extensionVersion: string,
): Promise<void> {
  await fetchJson<unknown>("/api/extension/telemetry", {
    method: "POST",
    body: event,
    auth: true,
    extensionVersion,
  });
}

/**
 * `GET /api/extension/status` — TODO(M3): this endpoint is authenticated
 * via the user's standard session JWT (`get_current_user_id`), which the
 * extension service worker does not hold. The frontend popup-like UI is
 * expected to read state from `chrome.storage.local` instead of calling
 * this helper. Exported only for completeness / future use once we have
 * a JWT-share channel.
 */
export async function getStatus(): Promise<ExtensionStatusResponse> {
  // Intentionally `auth: false` — see TODO above. Will 401 until we
  // wire a user JWT through.
  return fetchJson<ExtensionStatusResponse>("/api/extension/status");
}
