import os
from pathlib import Path
import tempfile
import unittest

from aiharness.repository_tools import RepositoryTools, ToolError


class RepositoryToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.tools = RepositoryTools(self.root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_list_and_summary_omit_secrets_and_generated_directories(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
        (self.root / ".env").write_text("AI_API_KEY=do-not-read\n", encoding="utf-8")
        (self.root / "private.pem").write_text("secret\n", encoding="utf-8")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "module.py").write_text("generated\n", encoding="utf-8")

        files = self.tools.list_files()

        self.assertEqual(files, ["src/app.py"])
        self.assertIn("src/app.py", self.tools.summary())
        self.assertNotIn("AI_API_KEY", self.tools.summary())

    def test_read_file_returns_utf8_text_and_rejects_secret_paths(self):
        (self.root / "README.md").write_text("hello\n", encoding="utf-8")
        (self.root / ".env").write_text("secret", encoding="utf-8")

        self.assertEqual(self.tools.read_file("README.md"), "hello\n")
        with self.assertRaises(ToolError):
            self.tools.read_file(".env")

    def test_read_file_rejects_binary_and_oversized_files(self):
        (self.root / "binary.dat").write_bytes(b"\xff\xfe")
        (self.root / "large.txt").write_text("12345", encoding="utf-8")
        small_limit_tools = RepositoryTools(self.root, max_file_bytes=4)

        with self.assertRaises(ToolError):
            self.tools.read_file("binary.dat")
        with self.assertRaises(ToolError):
            small_limit_tools.read_file("large.txt")

    def test_search_text_supports_case_insensitive_literal_matches(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text(
            "def OpenRouter():\n    return 'ready'\n", encoding="utf-8"
        )

        matches = self.tools.search_text("openrouter", case_sensitive=False)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].path, "src/main.py")
        self.assertEqual(matches[0].line, 1)

    def test_write_file_creates_parent_and_replaces_content(self):
        first_snapshot = self.tools.write_file("src/new.py", "answer = 42\n")
        second_snapshot = self.tools.write_file("src/new.py", "answer = 43\n")

        self.assertEqual(self.tools.read_file("src/new.py"), "answer = 43\n")
        snapshots = self.tools.list_snapshots()
        self.assertEqual({item["snapshot_id"] for item in snapshots}, {first_snapshot, second_snapshot})
        restored = self.tools.restore_snapshot(second_snapshot)
        self.assertEqual(self.tools.read_file("src/new.py"), "answer = 42\n")
        self.assertEqual(restored["restored"], second_snapshot)
        self.assertTrue(restored["rollback_snapshot"])

    def test_restoring_create_snapshot_removes_file_and_makes_rollback(self):
        snapshot_id = self.tools.write_file("new.txt", "created by agent")
        result = self.tools.restore_snapshot(snapshot_id)
        self.assertFalse((self.root / "new.txt").exists())
        self.assertIn(result["rollback_snapshot"], {item["snapshot_id"] for item in self.tools.list_snapshots()})

    def test_repository_map_and_project_instructions_are_bounded_and_readable(self):
        (self.root / "README.md").write_text("Project overview", encoding="utf-8")
        (self.root / "AGENTS.md").write_text("Project conventions", encoding="utf-8")
        file_map = self.tools.repository_map(max_chars=200)
        instructions = self.tools.project_instructions()
        self.assertIn("README.md", file_map)
        self.assertEqual(instructions, ("AGENTS.md", "Project conventions"))

    def test_paths_cannot_escape_repository_or_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            with self.assertRaises(ToolError):
                self.tools.read_file("../outside.txt")
            with self.assertRaises(ToolError):
                self.tools.read_file(str(outside))

            link = self.root / "outside-link.txt"
            link.symlink_to(outside)
            with self.assertRaises(ToolError):
                self.tools.read_file("outside-link.txt")

    def test_run_command_uses_repo_cwd_and_does_not_forward_api_key(self):
        previous_key = os.environ.get("AI_API_KEY")
        os.environ["AI_API_KEY"] = "must-not-reach-child"
        try:
            result = self.tools.run_command(
                [
                    os.sys.executable,
                    "-c",
                    "import os; print(os.getcwd()); print(os.getenv('AI_API_KEY', ''))",
                ]
            )
        finally:
            if previous_key is None:
                os.environ.pop("AI_API_KEY", None)
            else:
                os.environ["AI_API_KEY"] = previous_key

        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"].splitlines(), [str(self.root.resolve()), ""])

    def test_run_command_blocks_shells_and_destructive_commands(self):
        with self.assertRaises(ToolError):
            self.tools.run_command(["sh", "-c", "echo unsafe"])
        with self.assertRaises(ToolError):
            self.tools.run_command(["git", "push", "origin", "main"])


if __name__ == "__main__":
    unittest.main()
