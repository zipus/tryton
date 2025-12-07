"""Command-line entry point for Tuion."""

from __future__ import annotations

import argparse

from .app import run_app


def run() -> None:
    parser = argparse.ArgumentParser(description="Tuion: console Tryton client")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Launch in demo mode without contacting a server.",
    )
    args = parser.parse_args()
    run_app(demo=args.demo)


if __name__ == "__main__":  # pragma: no cover
    run()
