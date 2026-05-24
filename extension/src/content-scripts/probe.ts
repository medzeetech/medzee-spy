// Probe content script — minimal "is the extension installed?" beacon
// for the medzee-spy frontend (F8 / design §4.10, post-pivot 2026-05-24).
//
// Post-pivot the extension authenticates itself (popup login form) and is
// decoupled from the frontend's session. This script no longer auto-pairs
// or forwards commands; it just answers `medzee:probe` so the install
// screen can detect that the extension is present.

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
