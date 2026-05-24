"""Reports module — generation pipeline + REST endpoints (F3 + F4 + F5).

Reads captured WhatsApp messages from ``medzee_spy.captured_messages``
(populated by the F8 Chrome extension ingest endpoint), computes
deterministic metrics + LLM-generated insights, persists to
``medzee_spy.reports``, and exposes read + generate endpoints under
``/api/reports/*``.
"""
