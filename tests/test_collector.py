import os
import subprocess
import tempfile
import unittest
from datetime import datetime

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
        self.assertFalse(options["include_sensitive_files"])
        self.assertEqual(options["max_diff_lines"], 1200)
        self.assertEqual(options["max_diff_bytes"], 2 * 1024 * 1024)


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

            reports = collect_reports(
                config,
                "2026-06-28",
                include_current_changes=True,
            )

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["untracked_files"], ["src/draft.py"])
            self.assertEqual(reports[0]["staged_files"], [])
            self.assertEqual(reports[0]["unstaged_files"], [])
            self.assertEqual(reports[0]["repo_relative_path"], "sample-app")

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

            reports = collect_reports(
                config,
                "2026-06-28",
                include_current_changes=True,
            )

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["staged_files"], ["src/app.py"])
            self.assertIn("diff --git a/src/app.py b/src/app.py", reports[0]["staged_diff"])
            self.assertIn("+print('hello')", reports[0]["staged_diff"])

    def test_collect_reports_applies_the_configured_diff_byte_limit(self):
        with tempfile.TemporaryDirectory() as root_dir:
            repo_path = os.path.join(root_dir, "sample-app")
            os.mkdir(repo_path)
            subprocess.run(
                ["git", "init"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            with open(
                os.path.join(repo_path, "large.txt"),
                "w",
                encoding="utf-8",
            ) as file:
                file.write("x" * 10_000)
            subprocess.run(
                ["git", "add", "large.txt"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
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
                    "maxDiffLines": 0,
                    "maxDiffBytes": 128,
                },
            }

            reports = collect_reports(
                config,
                "2026-06-28",
                include_current_changes=True,
            )

            self.assertEqual(len(reports), 1)
            self.assertTrue(reports[0]["staged_diff_truncated"])
            self.assertIsNone(reports[0]["staged_diff_omitted_lines"])
            self.assertIn("128바이트 이후 diff 생략", reports[0]["staged_diff"])

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

            reports = collect_reports(
                config,
                "2026-06-28",
                include_current_changes=True,
            )

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["staged_files"], ["app.py"])
            self.assertEqual(reports[0]["staged_diff"], "")

    def test_historical_report_excludes_current_worktree_by_default(self):
        with tempfile.TemporaryDirectory() as root_dir:
            repo_path = os.path.join(root_dir, "sample-app")
            os.mkdir(repo_path)
            subprocess.run(
                ["git", "init"], cwd=repo_path, check=True, capture_output=True
            )
            with open(os.path.join(repo_path, "draft.py"), "w", encoding="utf-8") as f:
                f.write("draft\n")

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

            reports = collect_reports(config, "2020-01-01")

            self.assertEqual(reports, [])
            self.assertEqual(reports.warnings, [])
            self.assertEqual(reports.errors, [])

    def test_today_report_includes_current_worktree_by_default(self):
        with tempfile.TemporaryDirectory() as root_dir:
            repo_path = os.path.join(root_dir, "sample-app")
            os.mkdir(repo_path)
            subprocess.run(
                ["git", "init"], cwd=repo_path, check=True, capture_output=True
            )
            with open(os.path.join(repo_path, "draft.py"), "w", encoding="utf-8") as file:
                file.write("draft\n")
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

            reports = collect_reports(config, datetime.now().strftime("%Y-%m-%d"))

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["untracked_files"], ["draft.py"])

    def test_sensitive_files_are_excluded_unless_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as root_dir:
            repo_path = os.path.join(root_dir, "sample-app")
            os.mkdir(repo_path)
            subprocess.run(
                ["git", "init"], cwd=repo_path, check=True, capture_output=True
            )
            for name in (".env.local", ".env.example", "private.pem", "app.py"):
                with open(os.path.join(repo_path, name), "w", encoding="utf-8") as f:
                    f.write("value\n")

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

            reports = collect_reports(
                config, "2026-06-28", include_current_changes=True
            )
            self.assertEqual(
                reports[0]["untracked_files"],
                [".env.example", "app.py"],
            )

            config["report"] = {"includeSensitiveFiles": True}
            reports = collect_reports(
                config, "2026-06-28", include_current_changes=True
            )
            self.assertEqual(
                reports[0]["untracked_files"],
                [".env.example", ".env.local", "app.py", "private.pem"],
            )

    def test_fetch_failure_is_reported_but_local_changes_are_collected(self):
        with tempfile.TemporaryDirectory() as root_dir:
            repo_path = os.path.join(root_dir, "sample-app")
            os.mkdir(repo_path)
            subprocess.run(
                ["git", "init"], cwd=repo_path, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "remote", "add", "origin", os.path.join(root_dir, "missing")],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            with open(os.path.join(repo_path, "app.py"), "w", encoding="utf-8") as f:
                f.write("value\n")

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

            reports = collect_reports(
                config, "2026-06-28", include_current_changes=True
            )

            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["untracked_files"], ["app.py"])
            self.assertEqual(len(reports.warnings), 1)
            self.assertIn("git fetch 실패", reports.warnings[0]["message"])
            self.assertEqual(
                reports.warnings[0]["repo_relative_path"], "sample-app"
            )
            self.assertEqual(reports.errors, [])

    def test_nested_same_basename_reports_are_sorted_by_relative_path(self):
        with tempfile.TemporaryDirectory() as root_dir:
            for group in ("z", "a"):
                repo_path = os.path.join(root_dir, group, "app")
                os.makedirs(repo_path)
                subprocess.run(
                    ["git", "init"],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [
                        "git",
                        "remote",
                        "add",
                        "origin",
                        os.path.join(root_dir, "missing", group),
                    ],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                )
                with open(os.path.join(repo_path, "draft.py"), "w", encoding="utf-8") as file:
                    file.write(group)
            config = {
                "roots": [{
                    "name": "work",
                    "path": root_dir,
                    "maxDepth": 2,
                    "authorNames": ["Tester"],
                    "authorEmails": ["tester@example.com"],
                }],
                "outputDir": os.path.join(root_dir, "reports"),
                "exclude": [],
            }

            reports = collect_reports(
                config,
                "2026-06-28",
                include_current_changes=True,
            )

            self.assertEqual(
                [report["repo_relative_path"] for report in reports],
                ["a/app", "z/app"],
            )
            self.assertEqual(
                [warning["repo_relative_path"] for warning in reports.warnings],
                ["a/app", "z/app"],
            )


if __name__ == "__main__":
    unittest.main()
