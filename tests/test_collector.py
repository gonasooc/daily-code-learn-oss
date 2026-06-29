import os
import subprocess
import tempfile
import unittest

from lib.collector import collect_reports, _get_report_options, _truncate_diff


class CollectorDiffTests(unittest.TestCase):
    def test_truncate_diff_keeps_prefix_and_records_omitted_line_count(self):
        diff = "\n".join(["line 1", "line 2", "line 3", "line 4"])

        truncated, was_truncated, omitted = _truncate_diff(diff, 2)

        self.assertTrue(was_truncated)
        self.assertEqual(omitted, 2)
        self.assertIn("line 1\nline 2", truncated)
        self.assertIn("일부 diff 생략: 2줄", truncated)

    def test_truncate_diff_allows_unlimited_lines_when_max_is_zero(self):
        diff = "\n".join(["line 1", "line 2", "line 3"])

        truncated, was_truncated, omitted = _truncate_diff(diff, 0)

        self.assertEqual(truncated, diff)
        self.assertFalse(was_truncated)
        self.assertEqual(omitted, 0)

    def test_report_options_have_backwards_compatible_defaults(self):
        options = _get_report_options({})

        self.assertTrue(options["include_uncommitted_diff"])
        self.assertEqual(options["max_diff_lines"], 1200)


class CollectorIntegrationTests(unittest.TestCase):
    def test_collect_reports_includes_untracked_files(self):
        with tempfile.TemporaryDirectory() as root_dir:
            repo_path = os.path.join(root_dir, "sample-app")
            os.mkdir(repo_path)
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

            src_dir = os.path.join(repo_path, "src")
            os.mkdir(src_dir)
            with open(os.path.join(src_dir, "draft.py"), "w", encoding="utf-8") as f:
                f.write("print('draft')\n")

            config = {
                "roots": [{
                    "name": "tmp",
                    "path": root_dir,
                    "authorNames": ["Tester"],
                    "authorEmails": ["tester@example.com"],
                }],
                "outputDir": os.path.join(root_dir, "reports"),
                "exclude": [],
            }

            reports = collect_reports(config, "2026-06-28")

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["untracked_files"], ["src/draft.py"])
            self.assertEqual(reports[0]["staged_files"], [])
            self.assertEqual(reports[0]["unstaged_files"], [])

    def test_collect_reports_includes_staged_diff_by_default(self):
        with tempfile.TemporaryDirectory() as root_dir:
            repo_path = os.path.join(root_dir, "sample-app")
            os.mkdir(repo_path)
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

            src_dir = os.path.join(repo_path, "src")
            os.mkdir(src_dir)
            with open(os.path.join(src_dir, "app.py"), "w", encoding="utf-8") as f:
                f.write("print('hello')\n")

            subprocess.run(["git", "add", "src/app.py"], cwd=repo_path, check=True, capture_output=True)

            config = {
                "roots": [{
                    "name": "tmp",
                    "path": root_dir,
                    "authorNames": ["Tester"],
                    "authorEmails": ["tester@example.com"],
                }],
                "outputDir": os.path.join(root_dir, "reports"),
                "exclude": [],
                "report": {
                    "maxDiffLines": 100,
                },
            }

            reports = collect_reports(config, "2026-06-28")

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["staged_files"], ["src/app.py"])
            self.assertIn("diff --git a/src/app.py b/src/app.py", reports[0]["staged_diff"])
            self.assertIn("+print('hello')", reports[0]["staged_diff"])

    def test_collect_reports_can_disable_uncommitted_diff(self):
        with tempfile.TemporaryDirectory() as root_dir:
            repo_path = os.path.join(root_dir, "sample-app")
            os.mkdir(repo_path)
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

            with open(os.path.join(repo_path, "app.py"), "w", encoding="utf-8") as f:
                f.write("print('hello')\n")

            subprocess.run(["git", "add", "app.py"], cwd=repo_path, check=True, capture_output=True)

            config = {
                "roots": [{
                    "name": "tmp",
                    "path": root_dir,
                    "authorNames": ["Tester"],
                    "authorEmails": ["tester@example.com"],
                }],
                "outputDir": os.path.join(root_dir, "reports"),
                "exclude": [],
                "report": {
                    "includeUncommittedDiff": False,
                },
            }

            reports = collect_reports(config, "2026-06-28")

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["staged_files"], ["app.py"])
            self.assertEqual(reports[0]["staged_diff"], "")


if __name__ == "__main__":
    unittest.main()
