import unittest

from lib.git_commands import _filter_diff_excludes, _filter_excludes


class GitCommandFilterTests(unittest.TestCase):
    def test_filter_excludes_supports_substring_and_glob_patterns(self):
        files = [
            "src/app.py",
            "dist/app.js",
            "nested/foo.lock",
            "package-lock.json",
            "src/keep.ts",
        ]

        self.assertEqual(
            _filter_excludes(files, ["dist", "*.lock", "package-lock.json"]),
            ["src/app.py", "src/keep.ts"],
        )

    def test_filter_diff_removes_excluded_file_blocks(self):
        diff = "\n".join([
            "diff --git a/src/app.py b/src/app.py",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "diff --git a/dist/app.js b/dist/app.js",
            "--- a/dist/app.js",
            "+++ b/dist/app.js",
            "@@ -1 +1 @@",
            "-built",
            "+rebuilt",
        ])

        filtered = _filter_diff_excludes(diff, ["dist"])

        self.assertIn("src/app.py", filtered)
        self.assertIn("+new", filtered)
        self.assertNotIn("dist/app.js", filtered)
        self.assertNotIn("+rebuilt", filtered)

    def test_filter_diff_handles_paths_with_spaces(self):
        diff = "\n".join([
            "diff --git a/docs/generated file.md b/docs/generated file.md",
            "--- a/docs/generated file.md",
            "+++ b/docs/generated file.md",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "diff --git a/src/app.py b/src/app.py",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -1 +1 @@",
            "-old",
            "+new",
        ])

        filtered = _filter_diff_excludes(diff, ["docs/generated file.md"])

        self.assertNotIn("docs/generated file.md", filtered)
        self.assertIn("src/app.py", filtered)


if __name__ == "__main__":
    unittest.main()
