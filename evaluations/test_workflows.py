"""Deterministic end-to-end evaluations for core harness workflows."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from aiharness.agent import AgentError, CodingAgent
from aiharness.config import Settings
from aiharness.repository_tools import RepositoryTools


class ScriptedClient:
    """Offline model substitute that returns a prescribed sequence of tool calls."""

    def __init__(self, _settings, script):
        self.script = iter(script)

    def chat_completion(self, _messages, _tools):
        item = next(self.script)
        if isinstance(item, str):
            return {"choices": [{"message": {"role": "assistant", "content": item}}]}
        name, arguments = item
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": f"eval-{name}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }],
                }
            }]
        }


class WorkflowEvaluations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "README.md").write_text("evaluation fixture\n", encoding="utf-8")
        self.settings = Settings(
            api_key="offline-evaluation",
            model="scripted-evaluation",
            base_url="https://example.invalid/v1",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_script(self, script, *, prompt=None, max_tool_calls=20):
        with patch("aiharness.agent.OpenRouterClient", lambda settings: ScriptedClient(settings, script)):
            agent = CodingAgent(
                self.settings,
                RepositoryTools(self.root),
                permission_prompt=prompt,
                max_tool_calls=max_tool_calls,
            )
            final = agent.run("Run this deterministic evaluation scenario")
        return final

    def test_denied_edit_cannot_modify_the_repository(self):
        final = self.run_script(
            [
                ("write_file", {"path": "blocked.txt", "content": "must not exist"}),
                "Edit was denied.",
            ],
            prompt=lambda _action, _resource: "deny",
        )
        self.assertEqual(final, "Edit was denied.")
        self.assertFalse((self.root / "blocked.txt").exists())

    def test_failed_verification_can_be_followed_by_repair_and_pass(self):
        check_argv = [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; sys.exit(Path('result.txt').read_text() != 'ready\\n')",
        ]
        script = [
            ("write_file", {"path": "result.txt", "content": "not ready\n"}),
            ("run_command", {"argv": check_argv}),
            ("write_file", {"path": "result.txt", "content": "ready\n"}),
            ("run_command", {"argv": check_argv}),
            "Verification passed after repair.",
        ]
        command_results = []
        with patch("aiharness.agent.OpenRouterClient", lambda settings: ScriptedClient(settings, script)):
            agent = CodingAgent(
                self.settings,
                RepositoryTools(self.root),
                permission_prompt=lambda _action, _resource: "once",
                on_tool_result=lambda name, result: command_results.append(result)
                if name == "run_command" else None,
            )
            final = agent.run("Repair and verify the fixture")

        self.assertEqual(final, "Verification passed after repair.")
        self.assertEqual([result["returncode"] for result in command_results], [1, 0])
        self.assertEqual((self.root / "result.txt").read_text(encoding="utf-8"), "ready\n")
        self.assertEqual(len(agent.repository.list_snapshots()), 2)

    def test_tool_call_budget_stops_unbounded_scenarios(self):
        with patch(
            "aiharness.agent.OpenRouterClient",
            lambda settings: ScriptedClient(settings, [("list_files", {}), ("list_files", {})]),
        ):
            agent = CodingAgent(self.settings, RepositoryTools(self.root), max_tool_calls=1)
            with self.assertRaisesRegex(AgentError, "tool-call limit"):
                agent.run("List files repeatedly")


if __name__ == "__main__":
    unittest.main()
