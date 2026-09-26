"""Session-scoped permission checks for model-requested tools."""

from typing import Callable, Optional


READ_ACTIONS = {"list_files", "read_file", "search_text", "list_snapshots"}
EDIT_ACTIONS = {"write_file", "restore_snapshot"}
SHELL_ACTIONS = {"run_command"}


class PermissionManager:
    """Allow reads, ask for edits and commands, and support read-only review mode."""

    def __init__(
        self,
        *,
        mode: str = "build",
        prompt: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        if mode not in {"build", "review"}:
            raise ValueError("mode must be 'build' or 'review'")
        self.mode = mode
        self.prompt = prompt
        self._session_allow: set[tuple[str, str]] = set()
        self._session_deny: set[tuple[str, str]] = set()

    def request(self, action: str, resource: str) -> bool:
        if action == "read":
            return True
        if self.mode == "review" or action not in {"edit", "shell"}:
            return False
        key = (action, resource)
        if key in self._session_allow:
            return True
        if key in self._session_deny:
            return False
        if self.prompt is None:
            return False
        decision = self.prompt(action, resource).strip().lower()
        if decision in {"once", "allow", "y", "yes"}:
            return True
        if decision in {"always", "session"}:
            self._session_allow.add(key)
            return True
        self._session_deny.add(key)
        return False

    @staticmethod
    def action_for_tool(name: str) -> str:
        if name in READ_ACTIONS:
            return "read"
        if name in EDIT_ACTIONS:
            return "edit"
        if name in SHELL_ACTIONS:
            return "shell"
        return "deny"
