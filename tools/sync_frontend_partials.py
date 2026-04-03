from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.services.frontend_partials_sync import sync_frontend_partials


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync shared frontend partials into backend templates/partials.",
    )
    parser.add_argument("--backend-root", default=None, help="Backend repo root. Defaults to the current repo root.")
    parser.add_argument(
        "--frontend-root",
        default=os.getenv("FRONTEND_REPO_PATH", ""),
        help="Path to the frontend repo root. Falls back to FRONTEND_REPO_PATH.",
    )
    parser.add_argument(
        "--frontend-export-dir",
        default=os.getenv("FRONTEND_PARTIALS_EXPORT_DIR", ""),
        help="Explicit directory with exported backend partials. Falls back to FRONTEND_PARTIALS_EXPORT_DIR.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when the configured frontend partial source is unavailable.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    backend_root = Path(args.backend_root).resolve() if args.backend_root else REPO_ROOT
    result = sync_frontend_partials(
        backend_base_dir=backend_root,
        frontend_repo_path=args.frontend_root,
        frontend_export_dir=args.frontend_export_dir,
        strict=args.strict,
    )

    if result is None:
        print("Frontend partial sync skipped: source is not configured or not available.")
        return 0

    print(
        "Frontend partial sync complete: source={source_kind}; root={source_root}; written={written}; unchanged={unchanged}".format(
            source_kind=result.source_kind,
            source_root=result.source_root,
            written=len(result.written_files),
            unchanged=len(result.unchanged_files),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
