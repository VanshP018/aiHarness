import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiharness.agent import CodingAgent
from aiharness.config import Settings
from aiharness.repository_tools import RepositoryTools


class FakeOpenRouterClient:
    def __init__(self, _settings):
        self.turn = 0
        self.requests = []

    def chat_completion(self, messages, tools):
        self.requests.append((list(messages), list(tools)))
        self.turn += 1
        if self.turn == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"README.md"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "Done."}}]}


class CodingAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "README.md").write_text("Project context\n", encoding="utf-8")
        self.settings = Settings(api_key="test-key", model="test-model", base_url="https://example.test/v1")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_agent_executes_tool_then_returns_model_final(self):
        tool_calls = []
        with patch("aiharness.agent.OpenRouterClient", FakeOpenRouterClient):
            agent = CodingAgent(
                self.settings,
                RepositoryTools(self.root),
                on_tool_call=tool_calls.append,
            )
            result = agent.run("Summarize this project")

        self.assertEqual(result, "Done.")
        self.assertEqual(tool_calls, ["read_file"])
        self.assertEqual(len(agent.client.requests), 2)
        followup_messages = agent.client.requests[1][0]
        tool_result = next(message for message in followup_messages if message.get("role") == "tool")
        self.assertEqual(tool_result["tool_call_id"], "call-1")
        self.assertIn("Project context", tool_result["content"])

    def test_agent_can_write_repository_file_through_tool_call(self):
        class WriteClient:
            def __init__(self, _settings):
                self.turn = 0

            def chat_completion(self, _messages, _tools):
                self.turn += 1
                if self.turn == 1:
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{
                                    "id": "write-1",
                                    "type": "function",
                                    "function": {
                                        "name": "write_file",
                                        "arguments": json.dumps({
                                            "path": "src/answer.txt",
                                            "content": "answer = 42\n",
                                        }),
                                    },
                                }],
                            }
                        }]
                    }
                return {"choices": [{"message": {"role": "assistant", "content": "File written."}}]}

        with patch("aiharness.agent.OpenRouterClient", WriteClient):
            agent = CodingAgent(self.settings, RepositoryTools(self.root))
            result = agent.run("Create src/answer.txt")

        self.assertEqual(result, "File written.")
        self.assertEqual((self.root / "src" / "answer.txt").read_text(encoding="utf-8"), "answer = 42\n")

    def test_invalid_tool_arguments_are_returned_to_model_as_tool_error(self):
        class InvalidArgsClient:
            def __init__(self, _settings):
                self.turn = 0
                self.tool_result = None

            def chat_completion(self, messages, _tools):
                self.turn += 1
                if self.turn == 1:
                    return {
                        "choices": [{
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{
                                    "id": "bad-args",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": "{"},
                                }],
                            }
                        }]
                    }
                self.tool_result = next(message for message in messages if message.get("role") == "tool")
                return {"choices": [{"message": {"role": "assistant", "content": "Handled the tool error."}}]}

        with patch("aiharness.agent.OpenRouterClient", InvalidArgsClient):
            agent = CodingAgent(self.settings, RepositoryTools(self.root))
            result = agent.run("Read a file")

        self.assertEqual(result, "Handled the tool error.")
        self.assertIn("valid JSON", agent.client.tool_result["content"])

    def test_context_trimming_keeps_task_and_recent_complete_exchange(self):
        messages = [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "original task"},
            {
                "role": "assistant",
                "tool_calls": [{"id": "old-call", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "old-call", "content": "x" * 50_000},
            {
                "role": "assistant",
                "tool_calls": [{"id": "new-call", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "new-call", "content": "y" * 40_000},
        ]

        CodingAgent._trim_context(messages)

        self.assertEqual(messages[0]["content"], "instructions")
        self.assertEqual(messages[1]["content"], "original task")
        self.assertNotIn("old-call", json.dumps(messages))
        self.assertIn("new-call", json.dumps(messages))
        self.assertEqual(messages[-1]["tool_call_id"], "new-call")


if __name__ == "__main__":
    unittest.main()
