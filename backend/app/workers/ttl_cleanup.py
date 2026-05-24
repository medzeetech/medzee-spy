"""Background TTL cleanup worker for ``medzee_spy.captured_messages``.

After F8 (Chrome extension is the sole ingestion path), retention is
governed by a **rolling window**: any captured message older than
``CAPTURED_MESSAGES_TTL_DAYS`` (default 30) is hard-deleted regardless of
its parent WhatsApp session state. The legacy delete-on-session-disconnect
flow no longer applies — the extension's synthetic session row stays
``connected`` for the user's whole tenure.

Design notes:

* ``_run_once()`` is intentionally standalone-callable so tests can
  invoke it directly without driving the loop. The env var read happens
  at call-time so ``monkeypatch.setenv`` works.
* The loop catches every non-cancellation exception so a transient bug
  (e.g. DB hiccup) never kills the worker. Cancellation propagates as
  expected on shutdown.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _ttl_days() -> int:
    """Read at call-time so tests can monkeypatch env."""
    try:
        return int(os.environ.get("CAPTURED_MESSAGES_TTL_DAYS", "30"))
    except ValueError:
        return 30


_RUN_INTERVAL_S: float = 24 * 3600.0   # 1x por dia


async def _run_once() -> dict:
    """Performs one full cleanup pass. Returns stats dict for logging/tests.

    Deletes every ``captured_messages`` row whose ``ts`` is older than the
    rolling cutoff (``now - TTL_DAYS``). Uses the Supabase admin client so
    RLS is bypassed — captured rows are written via service_role too.
    """
    from app.clients.supabase import get_supabase_admin_client

    ttl_days = _ttl_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    cutoff_iso = cutoff.isoformat()

    def _delete() -> object:
        return (
            get_supabase_admin_client()
            .schema("medzee_spy")
            .table("captured_messages")
            .delete()
            .lt("ts", cutoff_iso)
            .execute()
        )

    result = await asyncio.to_thread(_delete)
    rows = getattr(result, "data", None) or []
    total_deleted = len(rows)
    logger.info(
        "ttl_cleanup.cycle_complete",
        extra={
            "total_deleted": total_deleted,
            "ttl_days": ttl_days,
            "cutoff": cutoff_iso,
        },
    )
    return {
        "total_deleted": total_deleted,
        "ttl_days": ttl_days,
    }


async def ttl_cleanup_loop() -> None:
    """Forever loop. Catches exceptions from ``_run_once`` so a transient bug
    never kills the worker. Stops cleanly when its asyncio.Task is cancelled."""
    while True:
        try:
            await _run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ttl_cleanup.unhandled")
        try:
            await asyncio.sleep(_RUN_INTERVAL_S)
        except asyncio.CancelledError:
            raise


__all__ = ["ttl_cleanup_loop", "_run_once"]
