/**
 * Shared wire types between the Medzee Spy backend, the Chrome extension,
 * and the frontend (F8 / design §4.2 + §4.10).
 *
 * Source of truth for the network shapes is
 * `backend/app/modules/extension/schemas.py`. Keep this file in sync
 * manually — there's no codegen pipeline yet. The matching Pydantic
 * models there use `extra='forbid'` so any drift surfaces as HTTP 422
 * during smoke (T25).
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

export interface ExtensionPairRequest {
  pairing_token: string;
  extension_install_id: string;
  extension_version?: string;
  user_agent?: string;
}

export interface ExtensionPairResponse {
  refresh_token: string;
  user_id: string;
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
// content scripts ↔ service worker. `WindowMedzeeMessage` flows over
// `window.postMessage` between the frontend page and the content scripts.

export type MedzeeRuntimeMessage =
  | { type: "medzee:get_state" }
  | { type: "medzee:pair"; payload: { pairing_token: string } }
  | { type: "medzee:start" }
  | { type: "medzee:abort" }
  | { type: "medzee:batch"; payload: ExtensionMessageBatch }
  | { type: "medzee:telemetry"; payload: ExtensionTelemetryEventPayload }
  | { type: "medzee:unpair" };

export type MedzeeRuntimeReply =
  | { type: "medzee:state"; paired: boolean; version: string }
  | { type: "medzee:ok" }
  | { type: "medzee:error"; code: string; message?: string };

export type WindowMedzeeMessage =
  | { type: "medzee:probe" }
  | { type: "medzee:cmd"; cmd: string; payload?: unknown }
  | { type: "medzee:installed"; paired: boolean; version: string }
  | {
      type: "medzee:event";
      event: TelemetryEvent | "batch_sent" | "aborted";
      data?: Record<string, unknown>;
    }
  | { type: "medzee:cmd_result"; cmd: string; result: unknown };
