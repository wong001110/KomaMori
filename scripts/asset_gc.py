#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))

from komamori.asset_gc import DEFAULT_DELETE_GRACE_SECONDS, audit_assets  # noqa: E402
from komamori.db import SessionLocal  # noqa: E402
from komamori.storage import get_asset_store  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit KomaMori assets and optionally remove safe old orphans.")
    parser.add_argument("--delete", action="store_true", help="Delete confirmed orphan files. Dry-run is the default.")
    parser.add_argument(
        "--grace-seconds",
        type=int,
        default=DEFAULT_DELETE_GRACE_SECONDS,
        help="Do not delete orphan files newer than this many seconds (default: 3600).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        report = audit_assets(
            session,
            get_asset_store(),
            delete=args.delete,
            grace_seconds=args.grace_seconds,
        )
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
