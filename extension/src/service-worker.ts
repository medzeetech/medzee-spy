// Medzee Spy — extension background service worker (MV3).
//
// Lifecycle: SW may terminate after 5 minutes idle. All persistent state lives
// in chrome.storage.local; in-flight collection progress is checkpointed so a
// re-wake can resume rather than restart.

import {
  ensureInstallId,
  getState,
  setState,
  clearState,
} from "./lib/storage.js";
import {
  pair as apiPair,
  sendBatch as apiSendBatch,
  sendTelemetry as apiSendTelemetry,
  PairingExpiredError,
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

const WA_WEB_URL = "https://web.whatsapp.com/";

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
  // Broadcast to medzee-spy frontend tabs so SpyFlowScreen / GeneratingScreen react.
  const tabs = await chrome.tabs.query({
    url: [
      "https://medzee.com/*",
      "https://*.medzee.com/*",
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

// --- pairing --------------------------------------------------------------

async function handlePair(pairingToken: string): Promise<MedzeeRuntimeReply> {
  try {
    const installId = await ensureInstallId();
    const resp = await apiPair({
      pairing_token: pairingToken,
      extension_install_id: installId,
      extension_version: EXT_VERSION,
      user_agent: navigator.userAgent,
    });
    await setState({
      refresh_token: resp.refresh_token,
      user_id: resp.user_id,
      extension_version: EXT_VERSION,
    });
    log("pair.success", { user_id: resp.user_id });
    return { type: "medzee:ok" };
  } catch (err) {
    log("pair.failed", { error: String(err) });
    await telemetry({
      event: "pairing_failed",
      extension_version: EXT_VERSION,
      reason: String(err).slice(0, 120),
    });
    return { type: "medzee:error", code: "pairing_failed", message: String(err) };
  }
}

// --- get_state ------------------------------------------------------------

async function handleGetState(): Promise<MedzeeRuntimeReply> {
  const state = await getState();
  return {
    type: "medzee:state",
    paired: !!state.refresh_token,
    version: EXT_VERSION,
  };
}

// --- start collection -----------------------------------------------------

async function handleStart(): Promise<MedzeeRuntimeReply> {
  const state = await getState();
  if (!state.refresh_token) {
    return { type: "medzee:error", code: "not_paired" };
  }

  // 1. Find or open web.whatsapp.com tab.
  const tabs = await chrome.tabs.query({ url: "https://web.whatsapp.com/*" });
  let waTab: chrome.tabs.Tab | undefined = tabs[0];
  if (!waTab) {
    waTab = await chrome.tabs.create({ url: WA_WEB_URL, active: true });
  } else if (waTab.id !== undefined) {
    await chrome.tabs.update(waTab.id, { active: true });
  }

  const waTabId = waTab?.id;
  if (waTabId === undefined) {
    return { type: "medzee:error", code: "tab_failed" };
  }

  // 2. Reset progress checkpoint.
  await setState({
    collection_in_progress: {
      batch_id: crypto.randomUUID(),
      total_batches: 0,
      batches_sent: 0,
      started_at: new Date().toISOString(),
    },
  });

  // 3. Tell the collector content-script to begin. It may take a moment for
  //    the content-script to be ready after a fresh tab.create — retry briefly.
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
  if (!state.refresh_token) {
    return { type: "medzee:error", code: "not_paired" };
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
    if (err instanceof PairingExpiredError) {
      log("batch.pairing_expired");
      await setState({ refresh_token: null });
      await emitToAllMedzeeTabs({
        type: "medzee:event",
        event: "pairing_failed",
        data: { reason: "refresh_token_expired" },
      });
      return { type: "medzee:error", code: "pairing_expired" };
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

// --- unpair ---------------------------------------------------------------

async function handleUnpair(): Promise<MedzeeRuntimeReply> {
  await clearState();
  log("unpair.cleared");
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
      case "medzee:pair":
        reply = await handlePair(message.payload.pairing_token);
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
      case "medzee:unpair":
        reply = await handleUnpair();
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
  await ensureInstallId();
});

chrome.runtime.onStartup.addListener(async () => {
  log("onStartup");
  await telemetry({
    event: "service_worker_woke",
    extension_version: EXT_VERSION,
  });
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
