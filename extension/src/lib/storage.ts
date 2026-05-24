/**
 * Typed wrapper around `chrome.storage.local` for the single
 * `medzee` key (F8 / design §4.10, post-pivot 2026-05-24).
 *
 * Post-pivot the extension authenticates against `/api/auth/login` and
 * stores the Supabase session directly. There is no longer an `install_id`
 * or standalone `refresh_token` — both are replaced by the `session`
 * record below.
 *
 * The MV3 service worker is allowed to die at any time, so:
 *  - reads always merge against `DEFAULT_STATE` (missing keys → safe defaults);
 *  - writes go through `setState(patch)` which first re-reads then merges,
 *    avoiding a `JSON.stringify` race when two handlers patch concurrently.
 */

export interface ExtensionSession {
  access_token: string;
  refresh_token: string;
  /** Unix epoch seconds. Computed at login as `now + expires_in`. */
  expires_at: number;
  user_id: string;
  email: string;
}

export interface MedzeePersistedState {
  /** Supabase session obtained via `/api/auth/login`. */
  session: ExtensionSession | null;
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
    /** Running total of msgs persisted across all batches in this run. */
    messages_sent: number;
    started_at: string;
    /** Human-readable progress step shown in the popup (PT-BR).
     *  Ex.: "Lendo conversas (45/71)", "Enviando lote 2/3", "Concluído". */
    current_step: string | null;
  } | null;
}

export const DEFAULT_STATE: MedzeePersistedState = {
  session: null,
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

/** Drop the entire persisted state (used on `medzee:logout`). */
export async function clearState(): Promise<void> {
  await chrome.storage.local.remove(STORAGE_KEY);
}
