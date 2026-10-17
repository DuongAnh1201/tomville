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
    p.add_argument("--config", type=Path, help="settings TOML file")
    p.add_argument("--board", help="github, tasks-md, or Markdown file path")
    p.add_argument("--board-check", type=float, metavar="SEC", help="GitHub board interval (minimum 10; default 60)")
    p.add_argument("--poll", type=float, metavar="SEC", help="fallback polling interval (default 1)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from tomville.tui.app import TomvilleApp  # import Textual only when the app runs

    from tomville.core.settings import load_reader_settings

    try:
        settings = load_reader_settings(args.project or Path.cwd(), config=args.config, source=args.board, check_seconds=args.board_check, poll_seconds=args.poll)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    TomvilleApp(project=args.project, settings=settings).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
