import unittest

from aiharness.permissions import PermissionManager


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


if __name__ == "__main__":
    unittest.main()
