"""Captured messages module (F4 forward-capture, F8 extension cutover).

Persists WhatsApp messages that arrive via the Chrome extension ingest
endpoint (``POST /api/extension/ingest``) so on-demand report generation
can read from DB.

TTL: rolling 30 days — any captured row older than
``CAPTURED_MESSAGES_TTL_DAYS`` is hard-deleted by the background worker in
``app/workers/ttl_cleanup.py``. Encrypted at rest by Supabase storage; RLS
owner-only for reads.
"""
