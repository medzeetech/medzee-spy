"""F4-T7: Background TTL cleanup worker for ``captured_messages``.

This worker periodically scans for WhatsApp sessions that have been in
``status='disconnected'`` for more than ``CAPTURED_MESSAGES_TTL_DAYS`` days
(default 30) and deletes the linked ``captured_messages`` rows.

Design notes (mirrors ``SessionStore._expire_loop`` for pattern parity):

* ``_run_once()`` is intentionally standalone-callable — tests (T20) will
  invoke it directly without driving the loop, and the env var read happens
  at call-time so ``monkeypatch.setenv`` works.
* The loop catches every non-cancellation exception so a transient bug
  (e.g. DB hiccup) never kills the worker. Cancellation propagates as
  expected on shutdown.
* TTL gating relies on ``whatsapp_sessions.updated_at`` (kept fresh by the
  DB trigger) plus a strict ``status='disconnected'`` filter — see the
  ``find_disconnected_before`` repo docstring for why ``expired/failed/
  consumed`` are intentionally excluded.
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
    """Performs one full cleanup pass. Returns stats dict for logging/tests."""
    from app.modules.whatsapp import repository as whatsapp_repo
    from app.modules.captured_messages import repository as captured_repo

    ttl_days = _ttl_days()
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    expired_sessions = await whatsapp_repo.find_disconnected_before(cutoff)
    total_deleted = 0
    for session_id in expired_sessions:
        deleted = await captured_repo.delete_for_session(session_id)
        total_deleted += deleted
        logger.info(
            "ttl_cleanup.session_cleared",
            extra={
                "session_id": str(session_id),
                "deleted": deleted,
            },
        )
    logger.info(
        "ttl_cleanup.cycle_complete",
        extra={
            "expired_session_count": len(expired_sessions),
            "total_deleted": total_deleted,
            "ttl_days": ttl_days,
        },
    )
    return {
        "expired_session_count": len(expired_sessions),
        "total_deleted": total_deleted,
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
