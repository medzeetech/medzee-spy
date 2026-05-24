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
// eslint-disable-next-line no-console
console.log(
  "%c[MEDZEE WA-COLLECTOR] MAIN-world script loaded ✓",
  "background:#FFA500;color:#000;padding:4px 8px;font-weight:bold",
);

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
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    const wpp = window.WPP;
    if (wpp?.webpack?.isReady) return wpp;
    if (wpp?.webpack?.onReady) {
      await new Promise<void>((resolve) => {
        wpp.webpack!.onReady(resolve);
      });
      if (window.WPP) return window.WPP;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
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
  let wpp: WPPGlobal;
  try {
    wpp = await waitForWPP();
  } catch (err) {
    postToContent({
      from: "medzee:wa-collector",
      type: "event",
      event: "collect_failed",
      reason: "wpp_not_ready",
      detail: String(err).slice(0, 100),
    });
    return;
  }

  if (!isLoggedIn(wpp)) {
    postToContent({ from: "medzee:wa-collector", type: "event", event: "wa_needs_login" });
    return;
  }

  if (!wpp.chat) {
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
    chats = await wpp.chat.list({ onlyUsers: false, withLabels: false });
  } catch (err) {
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

  // Chunk + emit each batch to content-script (which forwards to SW).
  const batches = chunkMessages(all, { extensionVersion: EXT_VERSION });
  for (const batch of batches) {
    postToContent({
      from: "medzee:wa-collector",
      type: "batch",
      payload: batch,
    });
    // Tiny pause to avoid flooding the SW; SW handles retry/backoff on errors.
    await new Promise((r) => setTimeout(r, 50));
  }

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
  if (d.cmd === "collect") void collectAll();
});

postToContent({ from: "medzee:wa-collector", type: "event", event: "loaded" });
