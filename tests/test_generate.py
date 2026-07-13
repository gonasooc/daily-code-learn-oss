import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import generate
from lib.collector import ReportCollection


def _report(repo_path):
    return {
        "project_name": "sample-app",
        "repo_relative_path": "sample-app",
        "repo_path": repo_path,
        "root_name": "work",
        "branch": "main",
        "author_names": ["Tester"],
        "commits": [],
        "staged_files": [],
        "unstaged_files": [],
        "untracked_files": ["draft.py"],
        "include_uncommitted_diff": True,
        "staged_diff": "",
        "unstaged_diff": "",
        "staged_diff_truncated": False,
        "unstaged_diff_truncated": False,
        "staged_diff_omitted_lines": 0,
        "unstaged_diff_omitted_lines": 0,
    }


class GenerateTests(unittest.TestCase):
    def test_selected_missed_day_forwards_options_and_preserves_scan_failure(self):
        args = SimpleNamespace(
            init=False,
            doctor=False,
            no_notify=False,
            verbose=False,
            check_missed=True,
            days=14,
            notify=True,
            include_current_changes=True,
            date=None,
        )
        config = {"outputDir": "./reports", "roots": []}
        complete_result = {
            "warnings": [],
            "errors": [],
            "activity_days": [],
            "missed_days": [],
            "start_date": "2026-06-15",
            "end_date": "2026-06-28",
        }
        stdout = io.StringIO()

        with patch.object(generate, "parse_args", return_value=args), \
                patch.object(generate, "load_config", return_value=config), \
                patch.object(
                    generate,
                    "collect_missed_days",
                    return_value=complete_result,
                ), \
                patch.object(
                    generate,
                    "pick_missed_day",
                    return_value="2026-06-28",
                ), \
                patch.object(
                    generate,
                    "generate_reports_for_date",
                    return_value=0,
                ) as generate_mock, \
                redirect_stdout(stdout):
            self.assertEqual(generate.main(), 0)

        generate_mock.assert_called_once_with(
            config,
            "2026-06-28",
            notify_after_generate=True,
            include_current_changes=True,
        )
        self.assertIn("reports/2026-06-28", stdout.getvalue())

        incomplete_result = dict(complete_result)
        incomplete_result["warnings"] = [{
            "root_name": "work",
            "repo_path": "/workspace/app",
            "message": "fetch failed",
        }]
        with patch.object(generate, "parse_args", return_value=args), \
                patch.object(generate, "load_config", return_value=config), \
                patch.object(
                    generate,
                    "collect_missed_days",
                    return_value=incomplete_result,
                ), \
                patch.object(
                    generate,
                    "pick_missed_day",
                    return_value="2026-06-28",
                ), \
                patch.object(
                    generate,
                    "generate_reports_for_date",
                    return_value=0,
                ), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(generate.main(), 1)

    def test_cancelled_missed_selection_fails_only_when_scan_is_incomplete(self):
        args = SimpleNamespace(
            init=False,
            doctor=False,
            no_notify=False,
            verbose=False,
            check_missed=True,
            days=30,
            notify=False,
            include_current_changes=False,
            date=None,
        )
        config = {"outputDir": "./reports", "roots": []}
        base_result = {
            "warnings": [],
            "errors": [],
            "activity_days": [],
            "missed_days": [],
            "start_date": "2026-05-30",
            "end_date": "2026-06-28",
        }

        with patch.object(generate, "parse_args", return_value=args), \
                patch.object(generate, "load_config", return_value=config), \
                patch.object(generate, "collect_missed_days", return_value=base_result), \
                patch.object(generate, "pick_missed_day", return_value=None):
            self.assertEqual(generate.main(), 0)

        incomplete_result = dict(base_result)
        incomplete_result["errors"] = [{
            "root_name": "work",
            "repo_path": "/workspace/app",
            "message": "scan failed",
        }]
        with patch.object(generate, "parse_args", return_value=args), \
                patch.object(generate, "load_config", return_value=config), \
                patch.object(generate, "collect_missed_days", return_value=incomplete_result), \
                patch.object(generate, "pick_missed_day", return_value=None):
            self.assertEqual(generate.main(), 1)

    def _create_committed_repo(self, root_path, project_name, email):
        repo_path = os.path.join(root_path, project_name)
        os.makedirs(repo_path)
        subprocess.run(
            ["git", "init"], cwd=repo_path, check=True, capture_output=True
        )
        with open(os.path.join(repo_path, "app.py"), "w", encoding="utf-8") as file:
            file.write("print('hello')\n")
        subprocess.run(
            ["git", "add", "app.py"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        env = os.environ.copy()
        env.update({
            "GIT_AUTHOR_NAME": "Tester",
            "GIT_AUTHOR_EMAIL": email,
            "GIT_AUTHOR_DATE": "2026-06-28T10:00:00+0000",
            "GIT_COMMITTER_NAME": "Tester",
            "GIT_COMMITTER_EMAIL": email,
            "GIT_COMMITTER_DATE": "2026-06-28T10:00:00+0000",
        })
        subprocess.run(
            ["git", "commit", "-m", "feat: sample"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            env=env,
        )
        return repo_path

    def test_collection_warning_returns_partial_failure_exit_code(self):
        warning = {
            "root_name": "work",
            "repo_path": "/workspace/sample-app",
            "repo_relative_path": "teams/alpha/sample-app",
            "message": "git fetch 실패",
        }
        reports = ReportCollection([], warnings=[warning])
        stdout = io.StringIO()

        with patch.object(generate, "collect_reports", return_value=reports), redirect_stdout(stdout):
            exit_code = generate.generate_reports_for_date(
                {"outputDir": "./reports"}, "2026-06-28"
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("git fetch 실패", stdout.getvalue())
        self.assertIn("[work] teams/alpha/sample-app", stdout.getvalue())
        self.assertIn("수집이 실패했거나 불완전", stdout.getvalue())

    def test_successful_reports_do_not_hide_partial_collection_status(self):
        warning = {
            "root_name": "work",
            "repo_path": "/workspace/other-app",
            "repo_relative_path": "other-app",
            "message": "git fetch 실패",
        }
        reports = ReportCollection(
            [_report("/workspace/sample-app")],
            warnings=[warning],
        )
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as output_dir, \
                patch.object(generate, "collect_reports", return_value=reports), \
                patch.object(
                    generate,
                    "write_report",
                    return_value=os.path.join(output_dir, "report.md"),
                ), \
                redirect_stdout(stdout):
            exit_code = generate.generate_reports_for_date(
                {"outputDir": output_dir},
                "2026-06-28",
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("1개 생성, 저장소 수집 불완전", stdout.getvalue())
        self.assertNotIn("총 1개 프로젝트 리포트 생성 완료", stdout.getvalue())

    def test_issue_printer_derives_relative_path_for_legacy_warning(self):
        warning = {
            "root_name": "work",
            "repo_path": "/workspace/work/teams/beta/sample-app",
            "message": "git fetch 실패",
        }
        config = {
            "roots": [{"name": "work", "path": "/workspace/work"}],
        }
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            generate._print_collection_issues([warning], [], config)

        self.assertIn("[work] teams/beta/sample-app", stdout.getvalue())

    def test_issue_printer_escapes_terminal_controls_in_untrusted_fields(self):
        warning = {
            "root_name": "work\x1b[31m",
            "repo_relative_path": "team\nforged",
            "message": "fetch failed\roverwritten",
        }
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            generate._print_collection_issues([warning], [])

        output = stdout.getvalue()
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\r", output)
        self.assertIn(r"[work\x1b[31m] team\nforged", output)
        self.assertIn(r"fetch failed\roverwritten", output)

    def test_notify_receives_only_files_written_in_current_run(self):
        with tempfile.TemporaryDirectory() as output_dir:
            repo_path = os.path.join(output_dir, "sample-app")
            reports = ReportCollection([_report(repo_path)])
            generated_path = os.path.join(output_dir, "generated.md")
            with open(generated_path, "w", encoding="utf-8") as file:
                file.write("report")

            with patch.object(generate, "collect_reports", return_value=reports), \
                    patch.object(generate, "write_report", return_value=generated_path), \
                    patch.object(generate, "notify", return_value=True) as notify_mock:
                exit_code = generate.generate_reports_for_date(
                    {"outputDir": output_dir},
                    "2026-06-28",
                    notify_after_generate=True,
                )

            self.assertEqual(exit_code, 0)
            notify_mock.assert_called_once_with(
                {"outputDir": output_dir},
                "2026-06-28",
                output_dir,
                file_paths=[generated_path],
            )

    def test_notification_failure_returns_failure_exit_code(self):
        reports = ReportCollection([_report("/workspace/sample-app")])
        with tempfile.TemporaryDirectory() as output_dir:
            generated_path = os.path.join(output_dir, "generated.md")
            with open(generated_path, "w", encoding="utf-8") as file:
                file.write("report")

            with patch.object(generate, "collect_reports", return_value=reports), \
                    patch.object(generate, "write_report", return_value=generated_path), \
                    patch.object(generate, "notify", return_value=False):
                exit_code = generate.generate_reports_for_date(
                    {"outputDir": output_dir},
                    "2026-06-28",
                    notify_after_generate=True,
                )

        self.assertEqual(exit_code, 1)

    def test_notification_exception_is_reported_as_failure(self):
        reports = ReportCollection([_report("/workspace/sample-app")])
        with tempfile.TemporaryDirectory() as output_dir:
            generated_path = os.path.join(output_dir, "generated.md")
            with open(generated_path, "w", encoding="utf-8") as file:
                file.write("report")
            stdout = io.StringIO()

            with patch.object(generate, "collect_reports", return_value=reports), \
                    patch.object(generate, "write_report", return_value=generated_path), \
                    patch.object(
                        generate,
                        "notify",
                        side_effect=OSError("secret-bot-token"),
                    ), \
                    redirect_stdout(stdout):
                exit_code = generate.generate_reports_for_date(
                    {"outputDir": output_dir},
                    "2026-06-28",
                    notify_after_generate=True,
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("알림 처리 실패", stdout.getvalue())
        self.assertNotIn("secret-bot-token", stdout.getvalue())

    def test_write_failure_is_isolated_and_returns_failure(self):
        reports = ReportCollection([_report("/workspace/sample-app")])
        stdout = io.StringIO()

        with patch.object(generate, "collect_reports", return_value=reports), \
                patch.object(generate, "write_report", side_effect=OSError("denied")), \
                patch.object(generate, "notify") as notify_mock, \
                redirect_stdout(stdout):
                exit_code = generate.generate_reports_for_date(
                    {"outputDir": "./reports"},
                    "2026-06-28",
                    notify_after_generate=True,
                )

        self.assertEqual(exit_code, 1)
        notify_mock.assert_not_called()
        self.assertIn("리포트 생성 실패", stdout.getvalue())
        self.assertNotIn("0개 프로젝트 리포트 생성 완료", stdout.getvalue())

    def test_runtime_filename_collision_cannot_silently_overwrite(self):
        first = _report("/workspace/first")
        second = _report("/workspace/second")
        second["repo_relative_path"] = "other/sample-app"
        reports = ReportCollection([first, second])
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as output_dir, \
                patch.object(generate, "collect_reports", return_value=reports), \
                patch.object(generate, "build_report_filename", return_value="same.md"), \
                patch.object(generate, "write_report", return_value=os.path.join(output_dir, "same.md")) as write_mock, \
                redirect_stdout(stdout):
            exit_code = generate.generate_reports_for_date(
                {"outputDir": output_dir},
                "2026-06-28",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(write_mock.call_count, 1)
        self.assertIn("리포트 파일명 충돌 감지", stdout.getvalue())

    def test_end_to_end_same_project_names_produce_two_private_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            work_root = os.path.join(directory, "work-root")
            personal_root = os.path.join(directory, "personal-root")
            os.makedirs(work_root)
            os.makedirs(personal_root)
            email = "tester@example.com"
            self._create_committed_repo(work_root, "sample-app", email)
            self._create_committed_repo(personal_root, "sample-app", email)
            output_dir = os.path.join(directory, "reports")
            config = {
                "roots": [
                    {
                        "name": "work",
                        "path": work_root,
                        "authorNames": ["Tester"],
                        "authorEmails": [email],
                    },
                    {
                        "name": "personal",
                        "path": personal_root,
                        "authorNames": ["Tester"],
                        "authorEmails": [email],
                    },
                ],
                "outputDir": output_dir,
                "exclude": [],
            }

            exit_code = generate.generate_reports_for_date(
                config,
                "2026-06-28",
                include_current_changes=False,
            )

            self.assertEqual(exit_code, 0)
            report_dir = os.path.join(output_dir, "2026-06-28")
            filenames = sorted(os.listdir(report_dir))
            self.assertEqual(len(filenames), 2)
            self.assertTrue(any(name.startswith("work--sample-app--") for name in filenames))
            self.assertTrue(any(name.startswith("personal--sample-app--") for name in filenames))
            for filename in filenames:
                path = os.path.join(report_dir, filename)
                with open(path, "r", encoding="utf-8") as file:
                    content = file.read()
                self.assertNotIn(directory, content)
                self.assertNotIn(email, content)
                self.assertIn("## 대상 날짜 커밋", content)
                self.assertEqual(stat_mode(path), 0o600)


def stat_mode(path):
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
