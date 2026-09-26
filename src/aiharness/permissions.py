"""Configurable permission policy for model-requested tools."""

import fnmatch
import json
from pathlib import Path
from typing import Callable, Optional, Sequence, Union


READ_ACTIONS = {"list_files", "read_file", "search_text", "list_snapshots"}
EDIT_ACTIONS = {"write_file", "restore_snapshot"}
SHELL_ACTIONS = {"run_command"}
POLICY_ACTIONS = {"read", "edit", "shell"}
POLICY_DECISIONS = {"allow", "ask", "deny"}


def load_permission_rules(path: Union[str, Path]) -> list[dict[str, str]]:
    """Load and validate a JSON policy containing an ordered rules array."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read permission policy: {exc}") from None
    if not isinstance(payload, dict) or set(payload) != {"rules"} or not isinstance(payload["rules"], list):
        raise ValueError("Permission policy must be a JSON object containing only a 'rules' array.")
    return PermissionManager._validate_rules(payload["rules"])


class PermissionManager:
    """Allow reads, ask for edits and commands, and support read-only review mode."""

    def __init__(
        self,
        *,
        mode: str = "build",
        prompt: Optional[Callable[[str, str], str]] = None,
        rules: Optional[Sequence[dict[str, str]]] = None,
    ) -> None:
        if mode not in {"build", "review"}:
            raise ValueError("mode must be 'build' or 'review'")
        self.mode = mode
        self.prompt = prompt
        self.rules = self._validate_rules(rules or [])
        self._session_allow: set[tuple[str, str]] = set()
        self._session_deny: set[tuple[str, str]] = set()

    def request(self, action: str, resource: str) -> bool:
        if action not in POLICY_ACTIONS:
            return False
        if self.mode == "review" and action != "read":
            return False
        decision = self._configured_decision(action, resource)
        if decision == "allow":
            return True
        if decision == "deny":
            return False
        if action == "read" and decision is None:
            return True
        if self.mode == "review" and action != "read":
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
    def _validate_rules(rules: Sequence[dict[str, str]]) -> list[dict[str, str]]:
        if len(rules) > 100:
            raise ValueError("Permission policy may contain at most 100 rules.")
        validated = []
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict) or set(rule) != {"action", "resource", "decision"}:
                raise ValueError(f"Permission rule {index + 1} must contain action, resource, and decision only.")
            action, resource, decision = rule["action"], rule["resource"], rule["decision"]
            if not isinstance(action, str) or not isinstance(decision, str):
                raise ValueError(f"Permission rule {index + 1} has invalid action or decision values.")
            if action not in POLICY_ACTIONS and action != "*":
                raise ValueError(f"Permission rule {index + 1} has an invalid action.")
            if not isinstance(resource, str) or not resource or len(resource) > 1000:
                raise ValueError(f"Permission rule {index + 1} has an invalid resource pattern.")
            if decision not in POLICY_DECISIONS:
                raise ValueError(f"Permission rule {index + 1} has an invalid decision.")
            validated.append({"action": action, "resource": resource, "decision": decision})
        return validated

    def _configured_decision(self, action: str, resource: str) -> Optional[str]:
        for rule in self.rules:
            if rule["action"] in {"*", action} and fnmatch.fnmatchcase(resource, rule["resource"]):
                return rule["decision"]
        return None

    @staticmethod
    def action_for_tool(name: str) -> str:
        if name in READ_ACTIONS:
            return "read"
        if name in EDIT_ACTIONS:
            return "edit"
        if name in SHELL_ACTIONS:
            return "shell"
        return "deny"
