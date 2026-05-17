"""Captured messages module (F4 forward-capture).

Persists WhatsApp messages that arrive via uazapi webhook so on-demand
report generation can read from DB instead of needing /chat/find history
pull (which doesn't work on uazapi free tier).

TTL: 30 days after the linked ``whatsapp_session`` disconnects
(see ``workers/ttl_cleanup.py``). Encrypted at rest by Supabase
storage; RLS owner-only for reads.

D4 of STATE.md was explicitly revoked for this module — see F4-21.
"""
