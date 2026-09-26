import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aiharness.event_log import RunEventLogger


class RunEventLoggerTests(unittest.TestCase):
    def test_logs_tool_names_and_outcomes_without_arguments_or_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "run" / "events.jsonl"
            logger = RunEventLogger(path)
            logger.on_tool_call("run_command")
            logger.on_tool_result("run_command", {
                "argv": ["python", "-c", "secret argument"],
                "returncode": 1,
                "stdout": "private output",
                "stderr": "failure details",
            })

            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["event"], "tool_call")
            self.assertEqual(records[1]["status"], "failed")
            self.assertEqual(records[1]["returncode"], 1)
            combined = path.read_text(encoding="utf-8")
            for private_value in ("secret argument", "private output", "failure details"):
                self.assertNotIn(private_value, combined)

    def test_logs_command_success_and_tool_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            logger = RunEventLogger(path)
            logger.on_tool_result("run_command", {"returncode": 0, "timed_out": False})
            logger.on_tool_result("write_file", {"error": "permission denied"})
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([record["status"] for record in records], ["passed", "error"])

    def test_rotates_at_configured_size_and_keeps_one_previous_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            logger = RunEventLogger(path)
            with patch("aiharness.event_log.MAX_EVENT_LOG_BYTES", 1):
                logger.on_tool_call("read_file")
                logger.on_tool_call("search_text")
            self.assertTrue(path.exists())
            self.assertTrue(logger.backup_path.exists())
            self.assertIn('"tool":"read_file"', logger.backup_path.read_text(encoding="utf-8"))
            self.assertIn('"tool":"search_text"', path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
