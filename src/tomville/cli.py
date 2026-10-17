"""Command line: `tomville` / `tmv`. Bare runs the office; options grow in M6."""

from __future__ import annotations

import argparse
from pathlib import Path

from tomville import __version__


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tomville",
        description="A retro game view of your agent team, built on top of herdr.",
    )
    p.add_argument("-V", "--version", action="version", version=f"tomville {__version__}")
    p.add_argument("-C", "--project", type=Path, default=None, metavar="DIR", help="project whose ville is shown (default: current folder)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from tomville.tui.app import TomvilleApp  # import Textual only when the app runs

    TomvilleApp(project=args.project).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
