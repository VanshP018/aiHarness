"""Command-line entry point for the AI coding harness."""

import argparse
import os
from pathlib import Path
import sys
from typing import Optional

from aiharness import __version__
from aiharness.agent import AgentError, CodingAgent
from aiharness.config import Settings
from aiharness.event_log import RunEventLogger
from aiharness.permissions import PermissionManager, load_permission_rules
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
    parser.add_argument(
        "--mode", choices=("build", "review"), default="build",
        help="Build mode asks before edits/commands; review mode is read-only",
    )
    parser.add_argument(
        "--list-snapshots", action="store_true",
        help="List saved pre-edit snapshots and exit",
    )
    parser.add_argument(
        "--restore", nargs="?", const="latest", metavar="SNAPSHOT_ID",
        help="Restore a snapshot (defaults to the latest); asks before changing files",
    )
    parser.add_argument(
        "--event-log", metavar="PATH",
        help="Append redacted tool activity as JSONL to this path (no task, arguments, or file contents)",
    )
    parser.add_argument(
        "--permissions-file", metavar="PATH",
        help="Load ordered JSON allow/ask/deny rules for tool actions and resources",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"Repository directory does not exist: {repo}", file=sys.stderr)
        return 2

    permission_rules = []
    if args.permissions_file:
        policy_path = Path(args.permissions_file).expanduser()
        if not policy_path.is_absolute():
            policy_path = repo / policy_path
        try:
            permission_rules = load_permission_rules(policy_path)
        except ValueError as exc:
            print(f"Invalid permissions file: {exc}", file=sys.stderr)
            return 2

    if args.inspect:
        try:
            print(RepositoryTools(repo).summary())
        except ToolError as exc:
            print(f"Repository inspection failed: {exc}", file=sys.stderr)
            return 2
        return 0

    repository = RepositoryTools(repo)
    if args.list_snapshots:
        for item in repository.list_snapshots():
            print(f"{item['snapshot_id']}  {item['path']}  {item['created_at']}")
        return 0
    if args.restore:
        permission_manager = PermissionManager(
            mode=args.mode,
            prompt=_permission_prompt if sys.stdin.isatty() else None,
            rules=permission_rules,
        )
        if not permission_manager.request("edit", args.restore):
            print("Snapshot restore declined; run this command in an interactive terminal to approve it.", file=sys.stderr)
            return 1
        try:
            result = repository.restore_snapshot(args.restore)
        except ToolError as exc:
            print(f"Snapshot restore failed: {exc}", file=sys.stderr)
            return 1
        print(f"Restored {result['path']} from {result['restored']} (rollback snapshot: {result['rollback_snapshot']})")
        return 0

    settings = Settings.from_environment()
    print(f"AI Harness v{__version__}")
    print(f"Repository: {repo}")
    mode_description = (
        "read-only" if args.mode == "review"
        else "policy-controlled" if args.permissions_file
        else "asks before edits and commands"
    )
    print(f"Mode: {args.mode} ({mode_description})")
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
            event_path = Path(args.event_log).expanduser() if args.event_log else None
            if event_path is not None and not event_path.is_absolute():
                event_path = repo / event_path
            event_logger = RunEventLogger(event_path) if event_path else None
            agent = CodingAgent(
                settings,
                repository,
                on_tool_call=lambda name: _on_tool_call(name, event_logger),
                mode=args.mode,
                permission_prompt=_permission_prompt,
                on_tool_result=lambda name, result: _on_tool_result(name, result, event_logger),
                permission_rules=permission_rules,
            )
            response = agent.run(task)
        except AgentError as exc:
            print(f"Agent stopped: {exc}", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"Could not initialize event log: {exc}", file=sys.stderr)
            return 2
        print("\nAgent result:\n")
        print(response)
    else:
        print("\nNo task supplied. Pass --task or provide task text on stdin.")
    return 0


def _permission_prompt(action: str, resource: str) -> str:
    safe = "".join(char if char.isprintable() else " " for char in resource)[:240]
    print(f"\nPermission requested: {action} {safe}")
    print("[o] allow once  [s] allow this exact action for this run  [d] deny")
    try:
        choice = input("Choose [o/s/d]: ").strip().lower()
    except EOFError:
        return "deny"
    return {"o": "once", "s": "session", "d": "deny"}.get(choice, "deny")


def _show_tool_result(name: str, result: object) -> None:
    if name == "write_file" and isinstance(result, dict) and result.get("snapshot_id"):
        print(f"Saved pre-edit snapshot: {result['snapshot_id']}")


def _on_tool_call(name: str, event_logger: Optional[RunEventLogger]) -> None:
    print(f"Tool call: {name}")
    if event_logger:
        try:
            event_logger.on_tool_call(name)
        except OSError as exc:
            print(f"Event log unavailable: {exc}", file=sys.stderr)


def _on_tool_result(name: str, result: object, event_logger: Optional[RunEventLogger]) -> None:
    if event_logger:
        try:
            event_logger.on_tool_result(name, result)
        except OSError as exc:
            print(f"Event log unavailable: {exc}", file=sys.stderr)
    _show_tool_result(name, result)
