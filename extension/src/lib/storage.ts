/**
 * Typed wrapper around `chrome.storage.local` for the single
 * `medzee` key (F8 / design §4.10). Everything the extension persists
 * lives in one record so that `chrome.storage.local.get(['medzee'])` is
 * the only call we make on cold service-worker wake-ups.
 *
 * The MV3 service worker is allowed to die at any time, so:
 *  - reads always merge against `DEFAULT_STATE` (missing keys → safe defaults);
 *  - writes go through `setState(patch)` which first re-reads then merges,
 *    avoiding a `JSON.stringify` race when two handlers patch concurrently.
 */

export interface MedzeePersistedState {
  /** Stable per-install UUID v4. Generated once on first run. */
  install_id: string | null;
  /** Long-lived refresh token (`typ=extension_refresh`, 30 day TTL). */
  refresh_token: string | null;
  /** Owning user UUID. Mirrors the JWT `sub` claim. */
  user_id: string | null;
  /** Mirror of `manifest.json:version`. Stored once at install time. */
  extension_version: string;
  /** ISO timestamp of the last completed collection. */
  last_collection_at: string | null;
  last_collection_message_count: number;
  /** Set while a collection run is in flight; cleared on completion or abort. */
  collection_in_progress: {
    batch_id: string;
    total_batches: number;
    batches_sent: number;
    started_at: string;
  } | null;
}

export const DEFAULT_STATE: MedzeePersistedState = {
  install_id: null,
  refresh_token: null,
  user_id: null,
  extension_version: "0.0.0",
  last_collection_at: null,
  last_collection_message_count: 0,
  collection_in_progress: null,
};

const STORAGE_KEY = "medzee";

/** Read the full persisted state, merged against safe defaults. */
export async function getState(): Promise<MedzeePersistedState> {
  const stored = await chrome.storage.local.get([STORAGE_KEY]);
  const raw = (stored?.[STORAGE_KEY] ?? {}) as Partial<MedzeePersistedState>;
  return { ...DEFAULT_STATE, ...raw };
}

/** Merge `patch` into the persisted state and return the new full state. */
export async function setState(
  patch: Partial<MedzeePersistedState>,
): Promise<MedzeePersistedState> {
  const current = await getState();
  const next: MedzeePersistedState = { ...current, ...patch };
  await chrome.storage.local.set({ [STORAGE_KEY]: next });
  return next;
}

/** Drop the entire persisted state (used on `medzee:unpair`). */
export async function clearState(): Promise<void> {
  await chrome.storage.local.remove(STORAGE_KEY);
}

/**
 * Lazily generate and persist the per-install id.
 * Safe to call from any context — multiple racing callers converge on
 * the first persisted value because the second `setState` call observes
 * the first one's write.
 */
export async function ensureInstallId(): Promise<string> {
  const state = await getState();
  if (state.install_id) return state.install_id;
  const newId = crypto.randomUUID();
  const persisted = await setState({ install_id: newId });
  // If a concurrent write landed first, prefer that value.
  return persisted.install_id ?? newId;
}
