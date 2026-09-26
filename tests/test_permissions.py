import unittest
import json
from pathlib import Path
import tempfile

from aiharness.permissions import PermissionManager, load_permission_rules


class PermissionManagerTests(unittest.TestCase):
    def test_reads_are_allowed_without_prompt_and_review_mode_is_read_only(self):
        permissions = PermissionManager()
        self.assertTrue(permissions.request("read", "repository"))
        review = PermissionManager(mode="review", prompt=lambda *_args: "once")
        self.assertTrue(review.request("read", "repository"))
        self.assertFalse(review.request("edit", "file.py"))

    def test_session_approval_is_scoped_to_action_and_resource(self):
        permissions = PermissionManager(prompt=lambda *_args: "session")
        self.assertTrue(permissions.request("edit", "src/app.py"))
        permissions.prompt = lambda *_args: "deny"
        self.assertTrue(permissions.request("edit", "src/app.py"))
        self.assertFalse(permissions.request("edit", "src/other.py"))
        self.assertFalse(permissions.request("shell", "[\"python\",\"-m\",\"pytest\"]"))

    def test_deny_is_cached_for_the_same_action_and_resource(self):
        prompts = []
        permissions = PermissionManager(prompt=lambda action, resource: prompts.append((action, resource)) or "deny")
        self.assertFalse(permissions.request("shell", "python -m pytest"))
        permissions.prompt = lambda *_args: "once"
        self.assertFalse(permissions.request("shell", "python -m pytest"))
        self.assertEqual(prompts, [("shell", "python -m pytest")])

    def test_ordered_policies_match_action_and_resource_glob(self):
        permissions = PermissionManager(rules=[
            {"action": "edit", "resource": "src/*.py", "decision": "allow"},
            {"action": "shell", "resource": "*pytest*", "decision": "deny"},
            {"action": "read", "resource": "private/*", "decision": "deny"},
        ])
        self.assertTrue(permissions.request("edit", "src/app.py"))
        self.assertFalse(permissions.request("edit", "README.md"))
        self.assertFalse(permissions.request("shell", '["python","-m","pytest"]'))
        self.assertFalse(permissions.request("read", "private/notes.txt"))
        self.assertTrue(permissions.request("read", "README.md"))

    def test_ask_rule_falls_back_to_prompt_and_review_cannot_be_overridden(self):
        prompts = []
        permissions = PermissionManager(
            mode="review",
            prompt=lambda action, resource: prompts.append((action, resource)) or "once",
            rules=[{"action": "edit", "resource": "*", "decision": "allow"}],
        )
        self.assertFalse(permissions.request("edit", "src/app.py"))
        self.assertEqual(prompts, [])
        asks = PermissionManager(
            prompt=lambda action, resource: prompts.append((action, resource)) or "once",
            rules=[{"action": "shell", "resource": "*", "decision": "ask"}],
        )
        self.assertTrue(asks.request("shell", "python -m pytest"))
        self.assertEqual(prompts[-1], ("shell", "python -m pytest"))

    def test_policy_file_loads_and_rejects_malformed_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy_path = Path(temporary) / "permissions.json"
            policy_path.write_text(json.dumps({"rules": [
                {"action": "edit", "resource": "src/*.py", "decision": "allow"},
            ]}), encoding="utf-8")
            loaded = load_permission_rules(policy_path)
            self.assertEqual(len(loaded), 1)
            policy_path.write_text('{"rules":[{"action":[],"resource":"*","decision":"allow"}]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_permission_rules(policy_path)


if __name__ == "__main__":
    unittest.main()
