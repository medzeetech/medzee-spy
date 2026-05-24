/**
 * Shared wire types between the Medzee Spy backend, the Chrome extension,
 * and the frontend (F8 / design §4.2 + §4.10, post-pivot 2026-05-24).
 *
 * Source of truth for the network shapes is
 * `backend/app/modules/extension/schemas.py`. Keep this file in sync
 * manually — there's no codegen pipeline yet. The matching Pydantic
 * models there use `extra='forbid'` so any drift surfaces as HTTP 422
 * during smoke (T25).
 *
 * Post-pivot (2026-05-24, 2nd iteration): the extension no longer has a
 * login form. The session is silently picked up from the frontend's
 * localStorage by a content script on `medzee-spy.vercel.app` and forwarded
 * to the service worker via `medzee:session_sync`. Auth on
 * `/api/extension/*` uses the standard Supabase access_token as Bearer.
 */

// ─── HTTP wire types (mirror of backend Pydantic models) ───────────────

export type ExtensionMessageType =
  | "text"
  | "image"
  | "audio"
  | "video"
  | "sticker"
  | "document"
  | "other";

export interface ExtensionMessage {
  /** WhatsApp chat id (e.g. `5511999999999@c.us` or `...@g.us`). */
  wa_chatid: string;
  /** Stable per-message id from WhatsApp Web (`WPP.msg.id._serialized`). */
  wa_msg_id: string;
  /** ISO 8601 UTC timestamp of the message. */
  ts: string;
  is_from_me: boolean;
  message_type: ExtensionMessageType;
  text?: string | null;
  contact_name?: string | null;
  wa_is_group?: boolean;
}

export interface ExtensionMessageBatch {
  /** UUID v4 generated once per collection run by the extension. */
  batch_id: string;
  /** 0..N-1 within this collection run. */
  batch_index: number;
  /** Total number of batches in this collection run (>=1). */
  total_batches: number;
  /** Mirror of `manifest.json:version`. Backend uses it for the
   *  `X-Extension-Version` floor check (CHX-14). */
  extension_version: string;
  messages: ExtensionMessage[];
}

/** Shape of the Supabase session picked up from the frontend's localStorage
 *  by the probe content-script (`sb-<ref>-auth-token`). Forwarded to the
 *  service worker via `medzee:session_sync`. */
export interface SupabaseSessionSnapshot {
  access_token: string;
  refresh_token: string;
  /** Absolute unix-seconds expiry. Supabase JS may omit this on older
   *  formats — service worker computes from `expires_in` when missing. */
  expires_at?: number;
  /** Some Supabase JS versions populate this instead of `expires_at`. */
  expires_in?: number;
  user: {
    id: string;
    email: string;
  };
}

export interface ExtensionStatusResponse {
  paired: boolean;
  last_collection_at: string | null;
  last_collection_message_count: number;
  extension_min_version: string;
}

export type TelemetryEvent =
  | "collect_failed"
  | "collect_started"
  | "collect_completed"
  | "wa_needs_login"
  | "service_worker_woke"
  | "pairing_failed";

export interface ExtensionTelemetryEventPayload {
  event: TelemetryEvent;
  extension_version: string;
  reason?: string;
  chats_total?: number;
  chats_processed?: number;
  duration_ms?: number;
  ua?: string;
}

// ─── Runtime messaging between extension contexts ──────────────────────
//
// `MedzeeRuntimeMessage` flows over `chrome.runtime.sendMessage` between
// content scripts ↔ service worker ↔ popup. `WindowMedzeeMessage` flows
// over `window.postMessage` between the frontend page and the content
// scripts.

export type MedzeeRuntimeMessage =
  | { type: "medzee:get_state" }
  /** Sent by the probe content-script on the frontend domain whenever it
   *  reads (or re-reads) the Supabase session from localStorage. `payload`
   *  is `null` when the user is logged out on the site. */
  | { type: "medzee:session_sync"; payload: SupabaseSessionSnapshot | null }
  /** User-initiated "Sair" from the popup. Clears the cached session in
   *  chrome.storage. Does NOT log the user out on the site. */
  | { type: "medzee:logout" }
  | { type: "medzee:start" }
  | { type: "medzee:abort" }
  | { type: "medzee:batch"; payload: ExtensionMessageBatch }
  | { type: "medzee:telemetry"; payload: ExtensionTelemetryEventPayload }
  /** Sent by the collector content-script as the wa-collector ticks
   *  through its stages. SW writes `step` into
   *  `collection_in_progress.current_step` so the popup reflects the
   *  live progress (read from chrome.storage.onChanged). */
  | { type: "medzee:progress_step"; step: string };

export type MedzeeRuntimeReply =
  | {
      type: "medzee:state";
      logged_in: boolean;
      email: string | null;
      version: string;
    }
  | { type: "medzee:ok" }
  | { type: "medzee:error"; code: string; message?: string };

export type WindowMedzeeMessage =
  | { type: "medzee:probe" }
  | { type: "medzee:installed"; version: string }
  | {
      type: "medzee:event";
      event: TelemetryEvent | "batch_sent" | "aborted";
      data?: Record<string, unknown>;
    };
