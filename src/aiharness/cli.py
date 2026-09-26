"""Command-line entry point for the AI coding harness."""

import argparse
import os
from pathlib import Path
import sys

from aiharness import __version__
from aiharness.agent import AgentError, CodingAgent
from aiharness.config import Settings
from aiharness.repository_tools import RepositoryTools, ToolError


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
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print a bounded inventory of the selected repository and exit",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"Repository directory does not exist: {repo}", file=sys.stderr)
        return 2

    if args.inspect:
        try:
            print(RepositoryTools(repo).summary())
        except ToolError as exc:
            print(f"Repository inspection failed: {exc}", file=sys.stderr)
            return 2
        return 0

    settings = Settings.from_environment()
    print(f"AI Harness v{__version__}")
    print(f"Repository: {repo}")
    print("Phase 4 agent orchestration is ready.")
    if settings.api_key:
        print("AI_API_KEY: configured")
    else:
        print("AI_API_KEY: not set (add it to the environment or local .env file)")
    print(f"AI_MODEL: {settings.model}")
    print(f"AI_BASE_URL: {settings.base_url}")

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
        print("\nStarting coding agent...")
        try:
            agent = CodingAgent(
                settings,
                RepositoryTools(repo),
                on_tool_call=lambda name: print(f"Tool call: {name}"),
            )
            response = agent.run(task)
        except AgentError as exc:
            print(f"Agent stopped: {exc}", file=sys.stderr)
            return 1
        print("\nAgent result:\n")
        print(response)
    else:
        print("\nNo task supplied. Pass --task or provide task text on stdin.")
    return 0
