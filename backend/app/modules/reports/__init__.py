"""Reports module — generation pipeline + REST endpoints (F3).

Consumes the F1 ``ExtractedPayload`` cached in the session store, computes
deterministic metrics + LLM-generated insights, persists to
``medzee_spy.reports``, and exposes read endpoints under ``/api/reports/*``.

Bridges:
* F1 ``app.workers.extract`` triggers ``app.workers.report.generate_report_pipeline``
  on extract success/partial (fire-and-forget).
* F2 ``app.modules.whatsapp.service.consume_extracted`` calls
  ``app.modules.reports.repository.link_user`` to attach the user to a row
  created by the worker.
"""
