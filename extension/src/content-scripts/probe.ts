// Probe content script — bridges medzee-spy frontend ↔ extension service worker.
// Injected on https://*.medzee.com/* and http://localhost:5173/* (manifest).
//
// Responsibilities:
//   1. Reply to window.postMessage({type:'medzee:probe'}) with install/paired state.
//   2. Forward window.postMessage({type:'medzee:cmd', ...}) commands to the service worker.
//   3. Auto-pair when a pairing_token is present in localStorage and not yet paired.

import type {
  MedzeeRuntimeMessage,
  MedzeeRuntimeReply,
  WindowMedzeeMessage,
} from "../lib/messages.js";

const EXT_VERSION = chrome.runtime.getManifest().version;

// --- helpers --------------------------------------------------------------

function postToPage(msg: WindowMedzeeMessage): void {
  window.postMessage(msg, "*");
}

async function askServiceWorker(message: MedzeeRuntimeMessage): Promise<MedzeeRuntimeReply> {
  try {
    return (await chrome.runtime.sendMessage(message)) as MedzeeRuntimeReply;
  } catch (err) {
    return { type: "medzee:error", code: "sw_unreachable", message: String(err) };
  }
}

interface PageProbeState {
  paired: boolean;
  version: string;
}

async function getProbeState(): Promise<PageProbeState> {
  const reply = await askServiceWorker({ type: "medzee:get_state" });
  if (reply.type === "medzee:state") {
    return { paired: reply.paired, version: reply.version };
  }
  return { paired: false, version: EXT_VERSION };
}

// --- listener -------------------------------------------------------------

function isMedzeeMessage(data: unknown): data is WindowMedzeeMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    typeof (data as { type?: unknown }).type === "string" &&
    (data as { type: string }).type.startsWith("medzee:")
  );
}

window.addEventListener("message", async (event) => {
  // SECURITY: only accept same-window messages (page sends to itself).
  if (event.source !== window) return;
  const data = event.data;
  if (!isMedzeeMessage(data)) return;

  switch (data.type) {
    case "medzee:probe": {
      const state = await getProbeState();
      postToPage({ type: "medzee:installed", paired: state.paired, version: state.version });
      return;
    }
    case "medzee:cmd": {
      // Map page-level cmd → SW runtime message.
      const cmd = data.cmd;
      const payload = data.payload;
      let runtimeMsg: MedzeeRuntimeMessage | null = null;
      if (
        cmd === "pair" &&
        payload &&
        typeof payload === "object" &&
        "pairing_token" in payload
      ) {
        runtimeMsg = {
          type: "medzee:pair",
          payload: {
            pairing_token: String((payload as { pairing_token: unknown }).pairing_token),
          },
        };
      } else if (cmd === "start_collection") {
        runtimeMsg = { type: "medzee:start" };
      } else if (cmd === "abort_collection") {
        runtimeMsg = { type: "medzee:abort" };
      } else if (cmd === "unpair") {
        runtimeMsg = { type: "medzee:unpair" };
      }
      if (!runtimeMsg) {
        postToPage({ type: "medzee:cmd_result", cmd, result: { ok: false, code: "unknown_cmd" } });
        return;
      }
      const reply = await askServiceWorker(runtimeMsg);
      postToPage({ type: "medzee:cmd_result", cmd, result: reply });
      return;
    }
    default:
      return; // ignore other types (events going page-ward originate elsewhere)
  }
});

// --- service-worker event forwarding -------------------------------------
// SW can emit lifecycle events (collect_started, batch_sent, wa_needs_login,
// aborted, collect_completed, collect_failed) via chrome.runtime.sendMessage
// to this tab. We re-post them to the page so the SpyFlowScreen /
// GeneratingScreen can react.

chrome.runtime.onMessage.addListener((message) => {
  if (typeof message !== "object" || message === null) return;
  const m = message as { type?: string };
  if (m.type === "medzee:event") {
    // Forward verbatim — types are already correct.
    postToPage(message as WindowMedzeeMessage);
  }
});

// --- auto-pair on load ---------------------------------------------------
// The content script runs in the isolated world, so it cannot read
// `window.medzee_spy.pairing_token` set by the page. Instead the frontend
// (T18 `injectPairingToken`) mirrors the token into `localStorage`, which
// IS accessible from the isolated world. If found, we attempt a silent
// re-pair against the service worker.

(async function autoPair() {
  try {
    const token = window.localStorage.getItem("medzee_spy:pairing_token");
    if (!token) return;

    const state = await getProbeState();
    if (state.paired) return; // already paired, no need

    const reply = await askServiceWorker({
      type: "medzee:pair",
      payload: { pairing_token: token },
    });
    if (reply.type === "medzee:ok") {
      // Successful auto-pair — nudge the UI to re-probe. Reuse the
      // `collect_started` sentinel since WindowMedzeeMessage only allows
      // TelemetryEvent + batch_sent + aborted on medzee:event.
      postToPage({ type: "medzee:event", event: "collect_started" });
    }
  } catch {
    // Silent — frontend will discover non-paired state via explicit probe.
  }
})();
