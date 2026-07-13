import os
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from unittest.mock import patch

from lib.git_commands import GitCommandError
from lib.missed_days import (
    _format_project_name,
    _has_report,
    _is_valid_date_input,
    collect_missed_days,
    pick_missed_day,
)
from lib.parallel import ParallelResults


class MissedDaysReportDetectionTests(unittest.TestCase):
    def test_direct_date_input_requires_zero_padded_iso_format(self):
        self.assertTrue(_is_valid_date_input("2026-06-28"))
        self.assertFalse(_is_valid_date_input("2026-6-28"))
        self.assertFalse(_is_valid_date_input("2026-02-30"))

    def test_analysis_files_do_not_count_as_project_reports(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            for name in ("analysis.md", "codex-analysis.md", "claude-analysis.md"):
                with open(os.path.join(report_dir, name), "w", encoding="utf-8") as f:
                    f.write("# analysis\n")

            self.assertFalse(_has_report(output_dir, "2026-06-28"))

    def test_generated_project_markdown_counts_as_report(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            with open(os.path.join(report_dir, "sample-app.md"), "w", encoding="utf-8") as f:
                f.write(
                    "# 2026-06-28 - sample-app\n\n"
                    "## 기본 정보\n"
                )

            self.assertTrue(_has_report(output_dir, "2026-06-28"))

    def test_identity_marked_project_markdown_counts_as_report(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            marker = "a" * 64
            with open(
                os.path.join(report_dir, "work--sample--1234567890abcdef.md"),
                "w",
                encoding="utf-8",
            ) as file:
                file.write(
                    "# 2026-06-28 - work/sample-app\n"
                    f"<!-- daily-code-learn-report:v1:{marker} -->\n"
                )

            self.assertTrue(_has_report(output_dir, "2026-06-28"))

    def test_date_shaped_note_without_report_marker_or_structure_is_ignored(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            with open(
                os.path.join(report_dir, "notes.md"),
                "w",
                encoding="utf-8",
            ) as file:
                file.write("# 2026-06-28 - notes\nmeeting notes\n")

            self.assertFalse(_has_report(output_dir, "2026-06-28"))

    def test_arbitrary_markdown_does_not_count_as_report(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            with open(os.path.join(report_dir, "notes.md"), "w", encoding="utf-8") as f:
                f.write("# Daily notes\n")

            self.assertFalse(_has_report(output_dir, "2026-06-28"))

    def test_report_for_another_date_does_not_count(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            with open(os.path.join(report_dir, "sample-app.md"), "w", encoding="utf-8") as f:
                f.write("# 2026-06-27 - work/sample-app\n")

            self.assertFalse(_has_report(output_dir, "2026-06-28"))

    def test_special_markdown_file_is_reported_without_being_opened(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            special_path = os.path.join(report_dir, "block.md")
            os.mkdir(special_path)
            errors = []

            self.assertFalse(_has_report(
                output_dir,
                "2026-06-28",
                on_error=lambda path, error: errors.append((path, error)),
            ))
            self.assertEqual(errors[0][0], special_path)
            self.assertIn("일반 Markdown 파일", str(errors[0][1]))

    def test_symlink_date_directory_is_not_followed(self):
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as outside_dir:
            with open(
                os.path.join(outside_dir, "report.md"),
                "w",
                encoding="utf-8",
            ) as file:
                file.write("# 2026-06-28 - external/repository\n")
            report_dir = os.path.join(output_dir, "2026-06-28")
            try:
                os.symlink(outside_dir, report_dir, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")
            errors = []

            self.assertFalse(_has_report(
                output_dir,
                "2026-06-28",
                on_error=lambda path, error: errors.append((path, error)),
            ))
            self.assertEqual(errors[0][0], report_dir)
            self.assertIsInstance(errors[0][1], OSError)

    def test_report_check_stays_on_open_directory_if_path_is_swapped(self):
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as outside_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            moved_dir = os.path.join(output_dir, "moved-date")
            os.makedirs(report_dir)
            with open(
                os.path.join(report_dir, "report.md"),
                "w",
                encoding="utf-8",
            ) as file:
                file.write(
                    "# 2026-06-28 - repository\n\n"
                    "## 기본 정보\n"
                )
            with open(
                os.path.join(outside_dir, "report.md"),
                "w",
                encoding="utf-8",
            ) as file:
                file.write("# external notes\n")
            real_listdir = os.listdir

            def swap_then_list(directory_fd):
                os.rename(report_dir, moved_dir)
                os.symlink(outside_dir, report_dir, target_is_directory=True)
                return real_listdir(directory_fd)

            try:
                with patch.object(
                    os,
                    "listdir",
                    side_effect=swap_then_list,
                ):
                    has_report = _has_report(output_dir, "2026-06-28")
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory swap unavailable: {error}")

            self.assertTrue(has_report)

    def test_report_directory_stat_error_is_surfaced(self):
        errors = []
        with patch(
            "lib.missed_days.os.open",
            side_effect=PermissionError("denied"),
        ):
            self.assertFalse(_has_report(
                "/reports",
                "2026-06-28",
                on_error=lambda path, error: errors.append((path, error)),
            ))

        self.assertEqual(errors[0][0], "/reports/2026-06-28")
        self.assertIn("denied", str(errors[0][1]))

    def test_nested_project_name_uses_root_relative_identity(self):
        root_path = os.path.join(os.sep, "workspace")
        repo_path = os.path.join(root_path, "group", "sample-app")

        self.assertEqual(
            _format_project_name("work", root_path, repo_path),
            "work/group/sample-app",
        )

    def test_extremely_long_numeric_selection_is_rejected_without_traceback(self):
        entry = {
            "date": "2026-06-28",
            "project_names": ["work/sample-app"],
            "project_count": 1,
            "commit_count": 1,
            "has_report": False,
        }
        answers = iter(["9" * 5000, "q"])
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            selected = pick_missed_day(
                {
                    "start_date": "2026-06-28",
                    "end_date": "2026-06-28",
                    "activity_days": [entry],
                    "missed_days": [entry],
                },
                1,
                input_func=lambda _prompt: next(answers),
            )

        self.assertIsNone(selected)
        self.assertIn("1부터 1 사이", stdout.getvalue())

    def test_project_names_are_safe_for_terminal_display(self):
        entry = {
            "date": "2026-06-28",
            "project_names": ["work/team\nforged\x1b[2J"],
            "project_count": 1,
            "commit_count": 1,
            "has_report": False,
        }
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            selected = pick_missed_day(
                {
                    "start_date": "2026-06-28",
                    "end_date": "2026-06-28",
                    "activity_days": [entry],
                    "missed_days": [entry],
                },
                1,
                input_func=lambda _prompt: "q",
            )

        self.assertIsNone(selected)
        self.assertNotIn("\x1b", stdout.getvalue())
        self.assertIn(r"work/team\nforged\x1b[2J", stdout.getvalue())


class MissedDaysErrorHandlingTests(unittest.TestCase):
    class _Progress:
        def update(self, _project, _status):
            pass

        def complete_one(self):
            pass

    def _collect_with_activity(self, output_dir, existing_errors=None):
        config = {
            "outputDir": output_dir,
            "roots": [{
                "name": "work",
                "path": os.path.join(os.sep, "workspace"),
                "authorEmails": ["dev@example.com"],
            }],
        }
        scan_errors = existing_errors or []

        def fake_parallel(_config, process_fn):
            value = process_fn(
                os.path.join(os.sep, "workspace", "sample-app"),
                config["roots"][0],
                self._Progress(),
            )
            return ParallelResults([value], errors=scan_errors)

        fetch_error = GitCommandError(
            os.path.join(os.sep, "workspace", "sample-app"),
            "fetch",
            "network unavailable",
        )
        with (
            patch("lib.missed_days.run_parallel_over_repos", side_effect=fake_parallel),
            patch("lib.missed_days.fetch", side_effect=fetch_error),
            patch(
                "lib.missed_days.get_commit_dates_by_author",
                return_value={"2026-06-28": 2},
            ),
        ):
            return collect_missed_days(
                config,
                days=1,
                today=date(2026, 6, 29),
            )

    def test_directory_listing_failure_is_reported_with_existing_errors(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            scan_error = {
                "repo_path": os.path.join(os.sep, "workspace", "broken"),
                "root_name": "work",
                "message": "저장소 탐색 실패",
            }

            with patch(
                "lib.missed_days.os.listdir",
                side_effect=PermissionError("permission denied"),
            ):
                result = self._collect_with_activity(output_dir, [scan_error])

            self.assertEqual(len(result["errors"]), 2)
            messages = [error["message"] for error in result["errors"]]
            self.assertIn("저장소 탐색 실패", messages)
            report_error = next(
                error for error in result["errors"]
                if "리포트 확인 실패" in error["message"]
            )
            self.assertIn("permission denied", report_error["message"])
            self.assertEqual(report_error["repo_relative_path"], "2026-06-28")
            self.assertEqual(len(result["warnings"]), 1)
            self.assertIn("git fetch 실패", result["warnings"][0]["message"])
            self.assertEqual(
                result["warnings"][0]["repo_relative_path"],
                "sample-app",
            )
            self.assertEqual([entry["date"] for entry in result["missed_days"]], ["2026-06-28"])

    def test_report_open_failure_is_reported_without_stopping_scan(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            notes_path = os.path.join(report_dir, "00-notes.md")
            with open(notes_path, "w", encoding="utf-8") as report_file:
                report_file.write("# notes\n")
            generated_path = os.path.join(report_dir, "zz-sample-app.md")
            with open(generated_path, "w", encoding="utf-8") as report_file:
                report_file.write(
                    "# 2026-06-28 - sample-app\n\n"
                    "## 기본 정보\n"
                )

            real_open = os.open

            def selective_open(path, *args, **kwargs):
                if path == os.path.basename(notes_path) and kwargs.get("dir_fd") is not None:
                    raise PermissionError("cannot read")
                return real_open(path, *args, **kwargs)

            with patch.object(os, "open", side_effect=selective_open):
                result = self._collect_with_activity(output_dir)

            self.assertEqual(len(result["errors"]), 1)
            self.assertEqual(result["errors"][0]["repo_path"], notes_path)
            self.assertIn("cannot read", result["errors"][0]["message"])
            self.assertEqual(result["missed_days"], [])
            self.assertTrue(result["activity_days"][0]["has_report"])


if __name__ == "__main__":
    unittest.main()
