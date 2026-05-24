"""Compatibility shim — re-exports from :mod:`app.workers.report`.

The reports tests' shared conftest patches ``app.modules.reports.worker.*``
defensively (so a ``from .repository import create_generating`` inside a
worker that lived under ``app.modules.reports`` would still see the fake).
The actual worker lives at ``app.workers.report`` (see F3 design § 12),
but ``pytest.MonkeyPatch.setattr`` with a dotted-string target requires
the *module* to be importable even when ``raising=False`` only suppresses
missing-*attribute* errors — so this module must exist for the conftest
to collect cleanly.

It intentionally contains nothing but a re-export of the public worker
entry point.
"""
from __future__ import annotations

from app.workers.report import generate_report_pipeline

__all__ = ["generate_report_pipeline"]
