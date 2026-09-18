from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2agg.pipeline import Pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="v2agg", description="V2Ray/Xray subscription aggregator")
    p.add_argument(
        "--settings",
        default="config/settings.yaml",
        help="Path to settings YAML",
    )
    p.add_argument(
        "--sources",
        default="config/sources.yaml",
        help="Path to sources YAML",
    )
    p.add_argument(
        "--mode",
        choices=["refresh", "nightly", "publish-only"],
        default="refresh",
        help="Pipeline mode",
    )
    p.add_argument(
        "--telegram-dry-run",
        action="store_true",
        help="Do not call Telegram API (log only)",
    )
    p.add_argument(
        "--print-metrics",
        action="store_true",
        help="Print metrics JSON to stdout at end",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path.cwd()
    settings = Path(args.settings)
    sources = Path(args.sources)
    if not settings.is_absolute():
        settings = root / settings
    if not sources.is_absolute():
        sources = root / sources

    pipe = Pipeline(
        settings,
        sources,
        mode=args.mode,
        dry_run_telegram=args.telegram_dry_run,
    )
    metrics = pipe.run()
    if args.print_metrics:
        print(json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
