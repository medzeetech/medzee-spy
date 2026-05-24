// Medzee Spy — extension background service worker (MV3).
//
// Lifecycle: SW may terminate after 5 minutes idle. All persistent state lives
// in chrome.storage.local; in-flight collection progress is checkpointed so a
// re-wake can resume rather than restart.
//
// Post-pivot (2026-05-24, 2nd iteration): silent session pickup. The probe
// content-script on the frontend domain reads the Supabase session from
// localStorage and pushes it to this worker via `medzee:session_sync`.
// We store it in chrome.storage and use the access_token as Bearer on
// `/api/extension/*`. No popup login form, no `/api/auth/login` call.

import {
  getState,
  setState,
  clearState,
} from "./lib/storage.js";
import {
  sendBatch as apiSendBatch,
  sendTelemetry as apiSendTelemetry,
  UnauthorizedError,
  ExtensionOutdatedError,
  RateLimitedError,
} from "./lib/api-client.js";
import type {
  ExtensionMessageBatch,
  ExtensionTelemetryEventPayload,
  MedzeeRuntimeMessage,
  MedzeeRuntimeReply,
  SupabaseSessionSnapshot,
  WindowMedzeeMessage,
} from "./lib/messages.js";

const EXT_VERSION = chrome.runtime.getManifest().version;

// --- helpers --------------------------------------------------------------

function log(event: string, extra: Record<string, unknown> = {}): void {
  // eslint-disable-next-line no-console
  console.log(`[medzee.sw] ${event}`, extra);
}

async function emitToPage(tabId: number, message: WindowMedzeeMessage): Promise<void> {
  try {
    await chrome.tabs.sendMessage(tabId, message);
  } catch {
    // Tab closed or no listener; safe to swallow.
  }
}

async function emitToAllMedzeeTabs(message: WindowMedzeeMessage): Promise<void> {
  // Broadcast to medzee-spy frontend tabs. Post-pivot the frontend is
  // decoupled from the extension, but the GeneratingScreen still benefits
  // from progress events when the user happens to have a Medzee tab open.
  const tabs = await chrome.tabs.query({
    url: [
      "https://medzee.com/*",
      "https://*.medzee.com/*",
      "https://medzee-spy.vercel.app/*",
      "http://localhost:5173/*",
    ],
  });
  for (const tab of tabs) {
    if (tab.id !== undefined) await emitToPage(tab.id, message);
  }
}

async function telemetry(payload: ExtensionTelemetryEventPayload): Promise<void> {
  try {
    await apiSendTelemetry(payload, EXT_VERSION);
  } catch (err) {
    log("telemetry.failed", { error: String(err) });
  }
}

// --- session sync / logout ------------------------------------------------

async function handleSessionSync(
  snapshot: SupabaseSessionSnapshot | null,
): Promise<MedzeeRuntimeReply> {
  // null payload = user is logged out on the site → wipe our cache.
  if (!snapshot) {
    const state = await getState();
    if (state.session) {
      log("session.cleared_from_site");
      await clearState();
    }
    return { type: "medzee:ok" };
  }

  const nowSec = Math.floor(Date.now() / 1000);
  const expiresAt =
    typeof snapshot.expires_at === "number"
      ? snapshot.expires_at
      : typeof snapshot.expires_in === "number"
        ? nowSec + snapshot.expires_in
        : nowSec + 3600; // conservative default; Supabase JS will refresh

  const existing = await getState();
  const existingToken = existing.session?.access_token;
  const incomingToken = snapshot.access_token;

  await setState({
    session: {
      access_token: incomingToken,
      refresh_token: snapshot.refresh_token,
      expires_at: expiresAt,
      user_id: snapshot.user.id,
      email: snapshot.user.email,
    },
    extension_version: EXT_VERSION,
  });

  if (existingToken !== incomingToken) {
    log("session.synced", { user_id: snapshot.user.id });
  }
  return { type: "medzee:ok" };
}

async function handleLogout(): Promise<MedzeeRuntimeReply> {
  // User clicked "Sair" in the popup. Wipes only our cached session — the
  // site session in localStorage is untouched, so the next probe sync will
  // re-populate it. To fully log out, the user needs to log out on the site.
  await clearState();
  log("logout.cleared");
  return { type: "medzee:ok" };
}

// --- get_state ------------------------------------------------------------

async function handleGetState(): Promise<MedzeeRuntimeReply> {
  const state = await getState();
  return {
    type: "medzee:state",
    logged_in: !!state.session,
    email: state.session?.email ?? null,
    version: EXT_VERSION,
  };
}

// --- start collection -----------------------------------------------------

async function handleStart(): Promise<MedzeeRuntimeReply> {
  const state = await getState();
  if (!state.session) {
    return { type: "medzee:error", code: "not_logged_in" };
  }

  // 1. Find an EXISTING web.whatsapp.com tab. We do NOT auto-open one —
  //    the popup has an explicit "Abrir WhatsApp Web" button for that.
  const tabs = await chrome.tabs.query({ url: "https://web.whatsapp.com/*" });
  const waTab = tabs[0];
  if (!waTab || waTab.id === undefined) {
    return {
      type: "medzee:error",
      code: "no_wa_tab",
      message: "Abra o WhatsApp Web antes de iniciar a análise.",
    };
  }
  const waTabId = waTab.id;

  // 2. Bring it to the front for visibility.
  try {
    await chrome.tabs.update(waTabId, { active: true });
  } catch {
    // Non-fatal — tab may have just been closed.
  }

  // 3. Reset progress checkpoint.
  await setState({
    collection_in_progress: {
      batch_id: crypto.randomUUID(),
      total_batches: 0,
      batches_sent: 0,
      messages_sent: 0,
      started_at: new Date().toISOString(),
    },
  });

  // 4. Tell the collector content-script to begin. It may take a moment for
  //    the content-script to be ready after a fresh tab — retry briefly.
  const begin = async (attempt = 0): Promise<void> => {
    try {
      await chrome.tabs.sendMessage(waTabId, { type: "medzee:begin_collection" });
    } catch (err) {
      if (attempt < 10) {
        await new Promise((r) => setTimeout(r, 500));
        return begin(attempt + 1);
      }
      log("start.collector_unreachable", { error: String(err) });
      await telemetry({
        event: "collect_failed",
        extension_version: EXT_VERSION,
        reason: "collector_unreachable",
      });
    }
  };
  void begin();

  log("start.dispatched", { tab_id: waTabId });
  await telemetry({ event: "collect_started", extension_version: EXT_VERSION });
  return { type: "medzee:ok" };
}

// --- abort collection -----------------------------------------------------

async function handleAbort(): Promise<MedzeeRuntimeReply> {
  await setState({ collection_in_progress: null });
  await emitToAllMedzeeTabs({ type: "medzee:event", event: "aborted" });
  log("abort.cleared");
  return { type: "medzee:ok" };
}

// --- batch ingestion ------------------------------------------------------

// Serial queue pra batches. Sem isso, 3 batches chegam em paralelo no SW,
// 3 POSTs em paralelo no backend, race condition: o batch final dispara
// trigger_generate ANTES dos batches anteriores terminarem insert no DB,
// resultando em relatório com poucas msgs persistidas naquele instante.
// Promise chain garante 1 batch processa de cada vez (FIFO pelo postMessage
// order do wa-collector).
let _batchQueue: Promise<unknown> = Promise.resolve();

function handleBatch(batch: ExtensionMessageBatch): Promise<MedzeeRuntimeReply> {
  const task = _batchQueue.then(() => _processBatch(batch));
  // Catch erros pra não quebrar a chain — cada batch é independente.
  _batchQueue = task.catch(() => undefined);
  return task;
}

async function _processBatch(batch: ExtensionMessageBatch): Promise<MedzeeRuntimeReply> {
  const state = await getState();
  if (!state.session) {
    return { type: "medzee:error", code: "not_logged_in" };
  }

  try {
    const resp = await apiSendBatch(batch, EXT_VERSION);

    // Update progress (count-based — order-independent, no longer assumes
    // 1000 msgs/batch). Final = received batches_sent reaches total_batches.
    const current = await getState();
    const progress = current.collection_in_progress;
    const batchesSent = (progress?.batches_sent ?? 0) + 1;
    const messagesSent =
      (progress?.messages_sent ?? 0) + batch.messages.length;
    const isFinal = batchesSent >= batch.total_batches;

    if (isFinal) {
      await setState({
        collection_in_progress: null,
        last_collection_at: new Date().toISOString(),
        last_collection_message_count: messagesSent,
      });
      await telemetry({
        event: "collect_completed",
        extension_version: EXT_VERSION,
        chats_total: undefined,
        chats_processed: undefined,
      });
      await emitToAllMedzeeTabs({ type: "medzee:event", event: "collect_completed" });
    } else {
      await setState({
        collection_in_progress: {
          batch_id: batch.batch_id,
          total_batches: batch.total_batches,
          batches_sent: batchesSent,
          messages_sent: messagesSent,
          started_at: progress?.started_at ?? new Date().toISOString(),
        },
      });
      await emitToAllMedzeeTabs({
        type: "medzee:event",
        event: "batch_sent",
        data: {
          batch_index: batch.batch_index,
          total_batches: batch.total_batches,
          received: resp.received ?? batch.messages.length,
        },
      });
    }
    log("batch.sent", {
      index: batch.batch_index,
      total: batch.total_batches,
      batches_sent_running: batchesSent,
      messages_sent_running: messagesSent,
      final: isFinal,
    });
    return { type: "medzee:ok" };
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      // Access token rejected — wipe the session so the popup forces re-login.
      log("batch.unauthorized");
      await clearState();
      await emitToAllMedzeeTabs({
        type: "medzee:event",
        event: "pairing_failed",
        data: { reason: "session_expired" },
      });
      return { type: "medzee:error", code: "unauthorized" };
    }
    if (err instanceof ExtensionOutdatedError) {
      log("batch.outdated", { min_version: err.min_version });
      await emitToAllMedzeeTabs({
        type: "medzee:event",
        event: "collect_failed",
        data: { reason: "extension_outdated", min_version: err.min_version },
      });
      return { type: "medzee:error", code: "extension_outdated", message: err.min_version };
    }
    if (err instanceof RateLimitedError) {
      log("batch.rate_limited");
      return { type: "medzee:error", code: "rate_limited" };
    }
    log("batch.failed", { error: String(err) });
    await telemetry({
      event: "collect_failed",
      extension_version: EXT_VERSION,
      reason: `batch_send_error: ${String(err).slice(0, 100)}`,
    });
    return { type: "medzee:error", code: "batch_failed", message: String(err) };
  }
}

// --- telemetry passthrough ------------------------------------------------

async function handleTelemetry(
  payload: ExtensionTelemetryEventPayload,
): Promise<MedzeeRuntimeReply> {
  await telemetry(payload);
  return { type: "medzee:ok" };
}

// --- runtime listener -----------------------------------------------------
// MUST return true synchronously to keep sendResponse channel open for async work.

function isRuntimeMessage(data: unknown): data is MedzeeRuntimeMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    typeof (data as { type?: unknown }).type === "string" &&
    (data as { type: string }).type.startsWith("medzee:")
  );
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!isRuntimeMessage(message)) return false;

  (async () => {
    let reply: MedzeeRuntimeReply;
    switch (message.type) {
      case "medzee:get_state":
        reply = await handleGetState();
        break;
      case "medzee:session_sync":
        reply = await handleSessionSync(message.payload);
        break;
      case "medzee:logout":
        reply = await handleLogout();
        break;
      case "medzee:start":
        reply = await handleStart();
        break;
      case "medzee:abort":
        reply = await handleAbort();
        break;
      case "medzee:batch":
        reply = await handleBatch(message.payload);
        break;
      case "medzee:telemetry":
        reply = await handleTelemetry(message.payload);
        break;
      default:
        reply = { type: "medzee:error", code: "unknown_message" };
    }
    sendResponse(reply);
  })().catch((err) => {
    log("listener.uncaught", { error: String(err) });
    sendResponse({ type: "medzee:error", code: "internal", message: String(err) });
  });

  return true; // keep channel open for async sendResponse
});

// --- lifecycle hooks ------------------------------------------------------

chrome.runtime.onInstalled.addListener(async (details) => {
  log("onInstalled", { reason: details.reason });
  await setState({ extension_version: EXT_VERSION });
});

chrome.runtime.onStartup.addListener(async () => {
  log("onStartup");
  const state = await getState();
  if (state.session) {
    await telemetry({
      event: "service_worker_woke",
      extension_version: EXT_VERSION,
    });
  }
});

// Detect tab closure of the WA Web tab mid-collection to publish an abort event.
chrome.tabs.onRemoved.addListener(async (tabId) => {
  const tabs = await chrome.tabs.query({ url: "https://web.whatsapp.com/*" });
  if (tabs.length > 0) return; // another WA tab still open
  const state = await getState();
  if (state.collection_in_progress) {
    log("tab_closed_mid_collection", { tab_id: tabId });
    await setState({ collection_in_progress: null });
    await emitToAllMedzeeTabs({
      type: "medzee:event",
      event: "aborted",
      data: { reason: "wa_tab_closed" },
    });
  }
});

log("service_worker.loaded", { version: EXT_VERSION });
