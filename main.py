"""CLI entry point.

Usage:
    python main.py                 # full pipeline (fetch + analyze + AI)
    python main.py --skip-ai       # everything except the Claude/Gemini calls
"""
from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="US stock market analysis backend")
    ap.add_argument("--skip-ai", action="store_true", help="skip Claude/Gemini calls")
    ap.add_argument("--kr-only", action="store_true",
                    help="refresh only the Korean market data (KIS API when keys set)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    _setup_logging(args.verbose)

    # Lazy imports so logging is configured first.
    if args.kr_only:
        from src import kr_refresh

        kr_refresh.run()
        return

    from src import pipeline

    pipeline.run(skip_ai=args.skip_ai)


if __name__ == "__main__":
    main()
