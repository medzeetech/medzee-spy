"""Programmatic orphan-instance purge for the uazapi tenant.

Lists every instance under the tenant via the admin endpoint and, with explicit
opt-in, resets each one (the equivalent of the dashboard's "Apagar Instância").
Useful when:
  - A device-limited plan accumulated leftovers from failed/half-finished
    sessions (e.g., crashes before the cleanup path ran).
  - You want a hard reset before a smoke test.

Usage (from `backend/`):

    # Inspect only — no destructive call:
    ./.venv/Scripts/python.exe scripts/cleanup_orphans.py --dry-run

    # Actually wipe — requires --yes to disarm the safety:
    ./.venv/Scripts/python.exe scripts/cleanup_orphans.py --yes

Reads env from backend/.env (UAZAPI_BASE_URL, UAZAPI_ADMIN_TOKEN).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make `app.*` importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.whatsapp.uazapi import UazapiProvider  # noqa: E402


async def _amain(*, dry_run: bool, force: bool) -> int:
    async with UazapiProvider() as provider:
        try:
            instances = await provider.list_all_instances()
        except Exception as exc:
            print(f"[error] could not list instances: {type(exc).__name__}: {exc}")
            return 2

        print(f"Found {len(instances)} instance(s) under the tenant.\n")
        for i, inst in enumerate(instances):
            inst_id = inst.get("id", "?")
            status = inst.get("status", "?")
            name = inst.get("name", "?")
            profile = inst.get("profileName") or "-"
            token = inst.get("token", "")
            token_tail = token[-6:] if token else "------"
            print(
                f"  [{i:>2}] id={inst_id:<20} status={status:<14} "
                f"name={name:<10} profile={profile}  token=...{token_tail}"
            )

        if not instances:
            print("\nNothing to do.")
            return 0

        if dry_run:
            print("\n--dry-run: not deleting anything.")
            return 0

        if not force:
            print(
                "\nRefusing to delete without --yes. Re-run with --yes to wipe "
                "the instances listed above."
            )
            return 1

        print("\nDeleting…")
        deleted = 0
        failed = 0
        for inst in instances:
            inst_id = inst.get("id", "?")
            token = inst.get("token")
            if not token:
                print(f"  [skip] {inst_id}: no token")
                failed += 1
                continue
            try:
                await provider.delete_instance(token)
                print(f"  [ok]   {inst_id}")
                deleted += 1
            except Exception as exc:
                print(f"  [fail] {inst_id}: {type(exc).__name__}: {exc}")
                failed += 1

        print(f"\nDone — deleted={deleted} failed={failed}")
        return 0 if failed == 0 else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List instances but do not delete (default behaviour without --yes).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually perform the destructive reset on every instance listed.",
    )
    args = parser.parse_args()

    if args.dry_run and args.yes:
        print("--dry-run and --yes are mutually exclusive.", file=sys.stderr)
        return 64

    return asyncio.run(_amain(dry_run=args.dry_run, force=args.yes))


if __name__ == "__main__":
    sys.exit(main())
