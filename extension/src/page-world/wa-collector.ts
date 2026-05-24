// Medzee Spy — page-world script injected into web.whatsapp.com.
//
// Runs in the SAME JS realm as WA Web. Uses @wppconnect/wa-js to read the
// decrypted Store. NEVER access chrome.* APIs here — content-script
// (T15) bridges via window.postMessage.
//
// Lifecycle:
//   1. Wait for wa-js's WPP.webpack.onReady (or its `wa-js:ready` event).
//   2. Listen for window.postMessage({from:'medzee:cmd', cmd:'collect'}).
//   3. On 'collect': enumerate chats → read last 30 days of messages →
//      chunk → post each batch back to content-script via window.postMessage.
//   4. Detect WA Web QR-not-logged-in state → post 'wa_needs_login' event.

import "@wppconnect/wa-js"; // self-attaches WPP global on load

import { chunkMessages } from "../lib/chunker.js";
import type { ExtensionMessage } from "../lib/messages.js";

// VERY VISIBLE marker — proves the page-world script actually loaded.
// If you see this in the web.whatsapp.com console, MAIN-world injection
// worked. If you DON'T see it, the script is being blocked somehow.
function mlog(stage: string, extra?: unknown): void {
  // eslint-disable-next-line no-console
  console.log(
    `%c[MEDZEE WA] ${stage}`,
    "background:#FFA500;color:#000;padding:3px 7px;font-weight:bold;border-radius:3px",
    extra ?? "",
  );
}

mlog("MAIN-world script loaded ✓");

const EXT_VERSION = "1.0.0"; // page-world has no chrome.runtime — version is hard-coded from manifest; T10 will keep sync.

// --- type aliases for the wa-js globals (loose; runtime may evolve) ------

interface WPPChatId {
  _serialized: string;
  user: string;
  server: string;
  fromMe?: boolean;
}

interface WPPChat {
  id: WPPChatId;
  name?: string;
  isGroup?: boolean;
  t?: number;
}

interface WPPMessage {
  id: { _serialized: string };
  body?: string;
  type?: string;
  t?: number; // seconds since epoch
  from?: string | WPPChatId;
  to?: string | WPPChatId;
  fromMe?: boolean;
  sender?: { pushname?: string };
  notifyName?: string;
}

interface WPPGlobal {
  webpack?: { onReady: (cb: () => void) => void; isReady?: boolean };
  chat?: {
    list: (opts?: { onlyUsers?: boolean; withLabels?: boolean }) => Promise<WPPChat[]>;
    getMessages: (chatId: string | WPPChatId, opts?: { count?: number }) => Promise<WPPMessage[]>;
  };
  conn?: { isAuthenticated?: () => boolean };
}

declare global {
  interface Window {
    WPP?: WPPGlobal;
  }
}

// --- helpers --------------------------------------------------------------

function postToContent(message: { from: "medzee:wa-collector"; [k: string]: unknown }): void {
  window.postMessage(message, "*");
}

function nowSec(): number {
  return Math.floor(Date.now() / 1000);
}

function thirtyDaysAgoSec(): number {
  return nowSec() - 30 * 24 * 60 * 60;
}

function inferMessageType(raw: string | undefined): ExtensionMessage["message_type"] {
  const t = (raw ?? "text").toLowerCase();
  if (t === "chat" || t === "text") return "text";
  if (t === "image") return "image";
  if (t === "audio" || t === "ptt") return "audio";
  if (t === "video") return "video";
  if (t === "sticker") return "sticker";
  if (t === "document") return "document";
  return "other";
}

function chatIdOf(chat: WPPChat): string {
  return chat.id?._serialized ?? "";
}

function safeContactName(chat: WPPChat): string | undefined {
  return chat.name ?? undefined;
}

function mapMessage(m: WPPMessage, chat: WPPChat): ExtensionMessage | null {
  if (!m.id?._serialized) return null;
  const tsSec = m.t ?? 0;
  if (tsSec === 0) return null;
  return {
    wa_chatid: chatIdOf(chat),
    wa_msg_id: m.id._serialized,
    ts: new Date(tsSec * 1000).toISOString(),
    is_from_me: !!m.fromMe,
    message_type: inferMessageType(m.type),
    text: m.body ?? null,
    contact_name: safeContactName(chat),
    wa_is_group: !!chat.isGroup,
  };
}

// --- wa-js readiness ------------------------------------------------------

async function waitForWPP(maxMs = 60_000): Promise<WPPGlobal> {
  mlog("waitForWPP: aguardando window.WPP…", { window_has_WPP: !!window.WPP });
  const start = Date.now();
  let dumped = false;

  while (Date.now() - start < maxMs) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const wpp = window.WPP as any;

    // Dump da estrutura na 1ª iteração — tira foto do que wa-js v4 expõe.
    if (!dumped && wpp && typeof wpp === "object") {
      dumped = true;
      mlog("waitForWPP: WPP root keys", { keys: Object.keys(wpp) });
      mlog("waitForWPP: WPP ready flags", {
        WPP_isReady: wpp.isReady,
        WPP_isFullReady: wpp.isFullReady,
        WPP_isInjected: wpp.isInjected,
        WPP_webpack_keys: wpp.webpack ? Object.keys(wpp.webpack) : null,
        WPP_webpack_isReady: wpp.webpack?.isReady,
        WPP_webpack_isInjected: wpp.webpack?.isInjected,
        WPP_webpack_onReady_type: typeof wpp.webpack?.onReady,
        WPP_has_on: typeof wpp.on === "function",
        WPP_has_onReady: typeof wpp.onReady,
      });
    }

    // Múltiplas checagens — pega qualquer formato conhecido de "ready".
    const isReady =
      wpp?.isReady === true ||
      wpp?.isFullReady === true ||
      wpp?.webpack?.isReady === true ||
      wpp?.webpack?.isFullReady === true;

    if (isReady) {
      mlog("waitForWPP: READY ✓", { elapsed_ms: Date.now() - start });
      return wpp;
    }

    await new Promise((r) => setTimeout(r, 500));
  }

  mlog("waitForWPP: TIMEOUT ✗", { elapsed_ms: maxMs });
  throw new Error("WPP not ready within timeout");
}

function isLoggedIn(wpp: WPPGlobal): boolean {
  try {
    if (typeof wpp.conn?.isAuthenticated === "function") {
      return !!wpp.conn.isAuthenticated();
    }
  } catch {
    // fall through to DOM heuristic
  }
  // Heuristic fallback: QR-code panel visible means not logged in.
  const qrPanel = document.querySelector('[data-testid="qrcode"], canvas[aria-label*="QR"], div[role="dialog"] canvas');
  return !qrPanel;
}

// --- collection -----------------------------------------------------------

async function collectAll(): Promise<void> {
  mlog("collectAll: START ▶");
  let wpp: WPPGlobal;
  try {
    wpp = await waitForWPP();
  } catch (err) {
    mlog("collectAll: WPP timeout — ABORT", { error: String(err) });
    postToContent({
      from: "medzee:wa-collector",
      type: "event",
      event: "collect_failed",
      reason: "wpp_not_ready",
      detail: String(err).slice(0, 100),
    });
    return;
  }

  mlog("collectAll: checando isLoggedIn…");
  if (!isLoggedIn(wpp)) {
    mlog("collectAll: NÃO logado — ABORT");
    postToContent({ from: "medzee:wa-collector", type: "event", event: "wa_needs_login" });
    return;
  }
  mlog("collectAll: logado ✓");

  if (!wpp.chat) {
    mlog("collectAll: WPP.chat AUSENTE — ABORT", { wpp_keys: Object.keys(wpp) });
    postToContent({
      from: "medzee:wa-collector",
      type: "event",
      event: "collect_failed",
      reason: "wpp_chat_missing",
    });
    return;
  }

  let chats: WPPChat[];
  try {
    mlog("collectAll: chamando WPP.chat.list({onlyUsers:false, withLabels:false})…");
    chats = await wpp.chat.list({ onlyUsers: false, withLabels: false });
    mlog("collectAll: chat.list retornou ✓", { count: chats.length });
  } catch (err) {
    mlog("collectAll: chat.list FALHOU — ABORT", { error: String(err) });
    postToContent({
      from: "medzee:wa-collector",
      type: "event",
      event: "collect_failed",
      reason: "chat_list_failed",
      detail: String(err).slice(0, 100),
    });
    return;
  }

  postToContent({
    from: "medzee:wa-collector",
    type: "event",
    event: "collect_started",
    chats_total: chats.length,
  });

  const cutoff = thirtyDaysAgoSec();
  const all: ExtensionMessage[] = [];
  let chatsProcessed = 0;

  for (const chat of chats) {
    chatsProcessed++;
    if (!chatIdOf(chat)) continue;

    let messages: WPPMessage[];
    try {
      // count=200 covers the last 30 days for typical conversations.
      messages = await wpp.chat.getMessages(chat.id, { count: 200 });
    } catch (err) {
      // Skip this chat but continue overall.
      postToContent({
        from: "medzee:wa-collector",
        type: "event",
        event: "chat_skipped",
        chat_id: chatIdOf(chat),
        reason: String(err).slice(0, 60),
      });
      continue;
    }

    for (const m of messages) {
      if ((m.t ?? 0) < cutoff) continue;
      const em = mapMessage(m, chat);
      if (em) all.push(em);
    }

    // Heartbeat every 5 chats so the content-script + SW can show progress.
    if (chatsProcessed % 5 === 0) {
      postToContent({
        from: "medzee:wa-collector",
        type: "event",
        event: "chat_progress",
        chats_processed: chatsProcessed,
        chats_total: chats.length,
        messages_so_far: all.length,
      });
    }
  }

  postToContent({
    from: "medzee:wa-collector",
    type: "event",
    event: "chats_done",
    chats_total: chats.length,
    messages_total: all.length,
  });

  mlog("collectAll: iteração de chats COMPLETA, enviando batches…", {
    chats_total: chats.length,
    messages_total: all.length,
  });

  // Chunk + emit each batch to content-script (which forwards to SW).
  const batches = chunkMessages(all, { extensionVersion: EXT_VERSION });
  mlog("collectAll: chunked em batches", { batches_count: batches.length });
  for (const batch of batches) {
    postToContent({
      from: "medzee:wa-collector",
      type: "batch",
      payload: batch,
    });
    // Tiny pause to avoid flooding the SW; SW handles retry/backoff on errors.
    await new Promise((r) => setTimeout(r, 50));
  }

  mlog("collectAll: DONE ✓");
  postToContent({
    from: "medzee:wa-collector",
    type: "event",
    event: "done",
    chats_total: chats.length,
    messages_total: all.length,
  });
}

// --- listener -------------------------------------------------------------

window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  const data = event.data;
  if (!data || typeof data !== "object") return;
  const d = data as { from?: unknown; cmd?: unknown };
  if (d.from !== "medzee:cmd") return;
  if (d.cmd === "collect") {
    mlog("recebido cmd 'collect' — iniciando collectAll");
    void collectAll();
  }
});

mlog("event listener registrado, aguardando cmd 'collect'");
postToContent({ from: "medzee:wa-collector", type: "event", event: "loaded" });
