// Medzee Spy — extension background service worker (MV3).
//
// Lifecycle: SW may terminate after 5 minutes idle. All persistent state lives
// in chrome.storage.local; in-flight collection progress is checkpointed so a
// re-wake can resume rather than restart.
//
// Post-pivot (2026-05-24): auth flow is email+password → `/api/auth/login`.
// The extension stores the resulting Supabase session itself; there is no
// more pairing token dance with the frontend.

import {
  getState,
  setState,
  clearState,
} from "./lib/storage.js";
import {
  login as apiLogin,
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

// --- login / logout -------------------------------------------------------

async function handleLogin(payload: {
  email: string;
  password: string;
}): Promise<MedzeeRuntimeReply> {
  try {
    const resp = await apiLogin(payload.email, payload.password);
    const nowSec = Math.floor(Date.now() / 1000);
    await setState({
      session: {
        access_token: resp.session.access_token,
        refresh_token: resp.session.refresh_token,
        expires_at: nowSec + resp.session.expires_in,
        user_id: resp.user.id,
        email: resp.user.email,
      },
      extension_version: EXT_VERSION,
    });
    log("login.success", { user_id: resp.user.id });
    return { type: "medzee:ok" };
  } catch (err) {
    log("login.failed", { error: String(err) });
    if (err instanceof UnauthorizedError) {
      return {
        type: "medzee:error",
        code: "invalid_credentials",
        message: "Email ou senha inválido",
      };
    }
    return {
      type: "medzee:error",
      code: "login_failed",
      message: String(err),
    };
  }
}

async function handleLogout(): Promise<MedzeeRuntimeReply> {
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

async function handleBatch(batch: ExtensionMessageBatch): Promise<MedzeeRuntimeReply> {
  const state = await getState();
  if (!state.session) {
    return { type: "medzee:error", code: "not_logged_in" };
  }

  try {
    const resp = await apiSendBatch(batch, EXT_VERSION);

    // Update progress
    const current = await getState();
    const progress = current.collection_in_progress;
    const batchesSent = (progress?.batches_sent ?? 0) + 1;
    const isFinal = batch.batch_index === batch.total_batches - 1;

    if (isFinal) {
      await setState({
        collection_in_progress: null,
        last_collection_at: new Date().toISOString(),
        last_collection_message_count:
          (progress?.batches_sent ?? 0) * 1000 + batch.messages.length,
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
    log("batch.sent", { index: batch.batch_index, total: batch.total_batches, final: isFinal });
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
      case "medzee:login":
        reply = await handleLogin(message.payload);
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
