// Probe + session-sync content script (F8 — pivot 2026-05-24, silent session pickup).
//
// Runs on medzee-spy frontend domains (manifest matches). Two jobs:
//
// 1. Read the Supabase auth session from `localStorage` on page load (and on
//    visibility-change) and forward it to the service worker via
//    `chrome.runtime.sendMessage({type:'medzee:session_sync', payload})`.
//    The SW stores it in `chrome.storage.local.session` and uses the
//    access_token as Bearer on all `/api/extension/*` calls.
//
//    No popup login form — the user is already authenticated on the site
//    (signup auto-logs in, or they came back through /login). The extension
//    simply picks up that session silently.
//
// 2. Answer `window.postMessage({type:'medzee:probe'})` so the install screen
//    on the site can detect that the extension is installed.

import type { MedzeeRuntimeMessage } from "../lib/messages.js";

// Supabase v2 stores the session at this key (derived from project ref in
// the URL). For Medzee Spy the ref is `itghmlcipjloirsyhare`.
const SUPABASE_PROJECT_REF = "itghmlcipjloirsyhare";
const STORAGE_KEY = `sb-${SUPABASE_PROJECT_REF}-auth-token`;

interface SupabaseSessionFromLocalStorage {
  access_token: string;
  refresh_token: string;
  expires_at?: number;
  expires_in?: number;
  user: { id: string; email: string };
}

function readSession(): SupabaseSessionFromLocalStorage | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const obj = parsed as Record<string, unknown>;
    if (typeof obj.access_token !== "string") return null;
    if (typeof obj.refresh_token !== "string") return null;
    const user = obj.user as Record<string, unknown> | undefined;
    if (!user || typeof user.id !== "string" || typeof user.email !== "string") {
      return null;
    }
    return {
      access_token: obj.access_token,
      refresh_token: obj.refresh_token,
      expires_at: typeof obj.expires_at === "number" ? obj.expires_at : undefined,
      expires_in: typeof obj.expires_in === "number" ? obj.expires_in : undefined,
      user: { id: user.id, email: user.email },
    };
  } catch {
    return null;
  }
}

async function syncSessionToSW(): Promise<void> {
  const session = readSession();
  const message: MedzeeRuntimeMessage = {
    type: "medzee:session_sync",
    payload: session,
  };
  try {
    await chrome.runtime.sendMessage(message);
  } catch {
    // SW may be transiently unreachable (cold start). Next visibility-change
    // will retry.
  }
}

// 1. Sync on load.
void syncSessionToSW();

// 2. Sync again whenever the tab becomes visible (user came back after
//    logging in / signing up elsewhere; Supabase refreshed the token).
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    void syncSessionToSW();
  }
});

// 3. Periodic re-sync every 30s as a defensive fallback — Supabase JS may
//    refresh the access_token in the background and we want the extension's
//    copy to stay fresh while this tab is open.
setInterval(() => {
  void syncSessionToSW();
}, 30_000);

// 4. Probe response — site can detect the extension is installed.
window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  const data = event.data as { type?: unknown } | null;
  if (!data || data.type !== "medzee:probe") return;
  window.postMessage(
    {
      type: "medzee:installed",
      version: chrome.runtime.getManifest().version,
    },
    "*",
  );
});
