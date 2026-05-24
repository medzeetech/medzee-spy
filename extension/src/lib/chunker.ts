/**
 * Batch `ExtensionMessage[]` into chunks of at most `maxPerBatch`
 * (default 1000), tagging every chunk with a shared `batch_id` and
 * monotonic `batch_index`/`total_batches`.
 *
 * Why the empty-array branch returns one empty batch:
 *   The backend ingest service uses `batch_index == total_batches - 1`
 *   to fire the F3 worker exactly once at the end of a collection
 *   (design §4.2 `service.ingest_batch`). If the extension finds zero
 *   messages we still need to nudge the worker so the user sees the
 *   `data_quality=insufficient` report path (D10) instead of a stuck
 *   "Generating…" screen.
 */
import type { ExtensionMessage, ExtensionMessageBatch } from "./messages.js";

export interface ChunkOptions {
  /** Defaults to 1000. */
  maxPerBatch?: number;
  /** Required: mirror of `manifest.json:version`. */
  extensionVersion: string;
}

export const DEFAULT_MAX_PER_BATCH = 1000;

export function chunkMessages(
  messages: ExtensionMessage[],
  opts: ChunkOptions,
): ExtensionMessageBatch[] {
  const max = opts.maxPerBatch ?? DEFAULT_MAX_PER_BATCH;
  if (max <= 0) {
    throw new Error(`chunkMessages: maxPerBatch must be > 0 (got ${max})`);
  }

  if (messages.length === 0) {
    // See header comment — even empty payloads produce 1 batch so the
    // backend can finalize the report.
    return [
      {
        batch_id: crypto.randomUUID(),
        batch_index: 0,
        total_batches: 1,
        extension_version: opts.extensionVersion,
        messages: [],
      },
    ];
  }

  const batch_id = crypto.randomUUID();
  const chunks: ExtensionMessage[][] = [];
  for (let i = 0; i < messages.length; i += max) {
    chunks.push(messages.slice(i, i + max));
  }
  const total_batches = chunks.length;
  return chunks.map((slice, i) => ({
    batch_id,
    batch_index: i,
    total_batches,
    extension_version: opts.extensionVersion,
    messages: slice,
  }));
}
