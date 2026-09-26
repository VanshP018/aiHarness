"""Phase 1 command-line entry point."""

import argparse
import os
from pathlib import Path
import sys

from aiharness import __version__
from aiharness.config import Settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aiharness",
        description="AI Harness Hackathon coding-agent harness",
    )
    parser.add_argument(
        "--repo",
        default=os.getcwd(),
        help="Repository to work on (default: current directory)",
    )
    parser.add_argument(
        "--task",
        help="Engineering task to execute; if omitted, enter it interactively",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"Repository directory does not exist: {repo}", file=sys.stderr)
        return 2

    settings = Settings.from_environment()
    print(f"AI Harness v{__version__}")
    print(f"Repository: {repo}")
    print("Phase 1 foundation is ready.")
    if settings.api_key:
        print("AI_API_KEY: configured")
    else:
        print("AI_API_KEY: not set (required for model-backed execution)")
    if settings.model:
        print(f"AI_MODEL: {settings.model}")
    else:
        print("AI_MODEL: not set (awaiting the model specified by the organisers)")

    task = args.task
    if task is None and sys.stdin.isatty():
        try:
            task = input("\nEnter an engineering task (or press Ctrl-D to exit): ").strip()
        except EOFError:
            print("\nExiting.")
            return 0
    elif task is None:
        task = sys.stdin.read().strip()

    if task:
        print("\nTask received. Agent execution will be added in Phase 2.")
        print(f"Task: {task}")
    else:
        print("\nNo task supplied. Pass --task or provide task text on stdin.")
    return 0
