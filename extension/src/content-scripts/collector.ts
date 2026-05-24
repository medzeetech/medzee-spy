// Medzee Spy — content script in web.whatsapp.com.
//
// Bridges the page-world wa-collector (which uses wa-js to read the Store)
// to the extension service worker. The wa-collector now runs as a
// MAIN-world content script (declared in manifest), bypassing the
// WhatsApp Web CSP that previously blocked `<script src=...>` injection.

import type {
  ExtensionMessageBatch,
  ExtensionTelemetryEventPayload,
  MedzeeRuntimeMessage,
} from "../lib/messages.js";

const EXT_VERSION = chrome.runtime.getManifest().version;

// --- Listen to page-world messages ----------------------------------------

interface PageWorldEvent {
  from: "medzee:wa-collector";
  type: "event" | "batch";
  event?: string;
  payload?: ExtensionMessageBatch;
  reason?: string;
  detail?: string;
  chats_total?: number;
  chats_processed?: number;
  messages_so_far?: number;
  messages_total?: number;
  chat_id?: string;
}

function isPageWorldMessage(data: unknown): data is PageWorldEvent {
  return (
    typeof data === "object" &&
    data !== null &&
    "from" in data &&
    (data as { from?: unknown }).from === "medzee:wa-collector"
  );
}

async function sendToSW(message: MedzeeRuntimeMessage): Promise<void> {
  try {
    await chrome.runtime.sendMessage(message);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[medzee.collector] SW unreachable", err);
  }
}

/** Map a wa-collector event to a short human label rendered in the popup.
 *  Returning null = no UI update (the event isn't user-facing). The labels
 *  mirror the console stages the user sees in DevTools, just compacted. */
function stepLabelFor(evt: PageWorldEvent): string | null {
  switch (evt.event) {
    case "loaded":
      return "Aguardando WhatsApp Web…";
    case "collect_started":
      return typeof evt.chats_total === "number"
        ? `Lendo ${evt.chats_total} conversa${evt.chats_total === 1 ? "" : "s"}…`
        : "Lendo conversas…";
    case "chat_progress":
      if (
        typeof evt.chats_processed === "number" &&
        typeof evt.chats_total === "number"
      ) {
        return `Lendo conversas (${evt.chats_processed}/${evt.chats_total})…`;
      }
      return "Lendo conversas…";
    case "chats_done":
      return typeof evt.messages_total === "number"
        ? `Empacotando ${evt.messages_total} mensagens…`
        : "Empacotando mensagens…";
    case "wa_needs_login":
      return "Faça login no WhatsApp Web";
    case "collect_failed":
      return `Erro: ${evt.reason ?? "falha na coleta"}`;
    case "done":
      return "Concluído ✓";
    default:
      return null;
  }
}

function telemetryPayloadFor(
  evt: PageWorldEvent
): ExtensionTelemetryEventPayload | null {
  switch (evt.event) {
    case "collect_started":
      return {
        event: "collect_started",
        extension_version: EXT_VERSION,
        chats_total: evt.chats_total,
      };
    case "collect_failed":
      return {
        event: "collect_failed",
        extension_version: EXT_VERSION,
        reason: `${evt.reason ?? "unknown"}${evt.detail ? `: ${evt.detail}` : ""}`.slice(0, 200),
      };
    case "wa_needs_login":
      return { event: "wa_needs_login", extension_version: EXT_VERSION };
    case "done":
      return {
        event: "collect_completed",
        extension_version: EXT_VERSION,
        chats_total: evt.chats_total,
      };
    default:
      return null;
  }
}

window.addEventListener("message", async (event) => {
  if (event.source !== window) return;
  const data = event.data;
  if (!isPageWorldMessage(data)) return;

  if (data.type === "batch" && data.payload) {
    await sendToSW({ type: "medzee:batch", payload: data.payload });
    return;
  }

  if (data.type === "event") {
    // Forward telemetry-worthy events to SW (which POSTs to /api/extension/telemetry).
    const tp = telemetryPayloadFor(data);
    if (tp) {
      await sendToSW({ type: "medzee:telemetry", payload: tp });
    }

    // Mirror the wa-collector stage onto the popup label (storage-driven).
    const stepLabel = stepLabelFor(data);
    if (stepLabel) {
      await sendToSW({ type: "medzee:progress_step", step: stepLabel });
    }

    // Special: wa_needs_login should also notify the medzee-spy frontend tabs
    // so SpyFlowScreen / GeneratingScreen can show the "logue no WhatsApp Web"
    // tela. SW handles broadcast to medzee.com tabs.
    if (data.event === "wa_needs_login") {
      // Service worker already gets it via telemetryPayloadFor. SW will also
      // broadcast a window-event to medzee tabs from its handleTelemetry path
      // (NOTE: SW currently does telemetry but does NOT broadcast wa_needs_login
      //  to medzee tabs from the telemetry handler — so we explicitly send a
      //  batch-like event hint via the existing broadcast helper. Simplest:
      //  rely on SW's onMessage handler to consume the telemetry and broadcast.
      //  For MVP, the SpyFlowScreen also polls /api/extension/status — eventual
      //  consistency is fine here.)
    }
  }
});

// --- 3. Listen to service worker commands --------------------------------

chrome.runtime.onMessage.addListener((message) => {
  if (typeof message !== "object" || message === null) return;
  const m = message as { type?: string };
  if (m.type === "medzee:begin_collection") {
    // Forward to page-world to kick off collection.
    window.postMessage({ from: "medzee:cmd", cmd: "collect" }, "*");
  }
});

// --- 4. Detect WA Web tab close mid-collection ---------------------------
// The SW already handles `chrome.tabs.onRemoved` for the WA tab; we don't need
// duplicate logic here. But pagehide (user navigating away within tab) is
// useful as an extra signal — fire and forget.

window.addEventListener("pagehide", () => {
  void sendToSW({ type: "medzee:abort" });
});

// eslint-disable-next-line no-console
console.log("[medzee.collector] content script loaded on", location.host);
