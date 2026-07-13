import errno
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import lib.renderer as renderer
from lib.renderer import build_report_filename, render_markdown, write_report


def _base_report(**overrides):
    report = {
        "project_name": "sample-app",
        "root_name": "work",
        "repo_relative_path": "team/sample-app",
        "repo_path": "/workspace/sample-app",
        "branch": "main",
        "author_names": ["Sample"],
        "commits": [],
        "staged_files": [],
        "unstaged_files": [],
        "untracked_files": [],
        "include_uncommitted_diff": True,
        "staged_diff": "",
        "unstaged_diff": "",
        "staged_diff_truncated": False,
        "unstaged_diff_truncated": False,
        "staged_diff_omitted_lines": 0,
        "unstaged_diff_omitted_lines": 0,
    }
    report.update(overrides)
    return report


class RendererTests(unittest.TestCase):
    def test_renders_work_summary_and_uncommitted_diff(self):
        report = _base_report(
            staged_files=["src/app.py"],
            staged_diff="\n".join([
                "diff --git a/src/app.py b/src/app.py",
                "+print('hello')",
            ]),
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertIn("## 작업 요약", markdown)
        self.assertIn("- Staged: 1 files", markdown)
        self.assertIn("### Staged", markdown)
        self.assertIn("- `src/app.py`", markdown)
        self.assertIn("<summary>staged diff 보기</summary>", markdown)
        self.assertIn("+print('hello')", markdown)
        self.assertIn("- 저장소: `work/team/sample-app`", markdown)
        self.assertNotIn("/workspace/sample-app", markdown)
        self.assertNotIn("sample@example.com", markdown)

    def test_renders_untracked_file_list_without_diff(self):
        report = _base_report(
            untracked_files=["src/draft.py"],
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertIn("- Untracked: 1 files", markdown)
        self.assertIn("### Untracked", markdown)
        self.assertIn("- `src/draft.py`", markdown)
        self.assertNotIn("<summary>untracked diff 보기</summary>", markdown)

    def test_renders_file_list_only_when_uncommitted_diff_is_disabled(self):
        report = _base_report(
            include_uncommitted_diff=False,
            unstaged_files=["src/app.py"],
            unstaged_diff="diff --git a/src/app.py b/src/app.py",
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertIn("### Unstaged", markdown)
        self.assertIn("- `src/app.py`", markdown)
        self.assertIn("- diff: 설정에서 비활성화됨", markdown)
        self.assertNotIn("<summary>unstaged diff 보기</summary>", markdown)

    def test_renders_truncated_notices_for_commit_and_uncommitted_diff(self):
        report = _base_report(
            commits=[{
                "hash": "abcdef123456",
                "date": "2026-06-28 10:30:00 +0900",
                "subject": "feat: sample",
                "files_changed": 1,
                "insertions": 2,
                "deletions": 1,
                "diff": "diff --git a/a.py b/a.py",
                "diff_truncated": True,
                "diff_omitted_lines": 3,
            }],
            staged_files=["src/app.py"],
            staged_diff="diff --git a/src/app.py b/src/app.py",
            staged_diff_truncated=True,
            staged_diff_omitted_lines=4,
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertIn("- Diff: 일부 diff 생략 (3줄)", markdown)
        self.assertIn("- Diff: 일부 diff 생략 (4줄)", markdown)

    def test_unknown_omitted_count_uses_a_limit_neutral_notice(self):
        report = _base_report(
            commits=[{
                "hash": "abcdef123456",
                "date": "2026-06-28 10:30:00 +0900",
                "subject": "feat: bounded diff",
                "files_changed": 1,
                "insertions": 1,
                "deletions": 0,
                "diff": "... 최대 32바이트 이후 diff 생략 ...",
                "diff_truncated": True,
                "diff_omitted_lines": None,
            }],
            staged_files=["src/app.py"],
            staged_diff="... 최대 32바이트 이후 diff 생략 ...",
            staged_diff_truncated=True,
            staged_diff_omitted_lines=None,
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertEqual(
            markdown.count("- Diff: 설정된 크기 또는 줄 수 제한 이후 생략"),
            2,
        )

    def test_report_filename_is_deterministic_and_collision_safe(self):
        first = _base_report(root_name="work", repo_relative_path="team/sample-app")
        second = _base_report(root_name="personal", repo_relative_path="sample-app")
        nested = _base_report(root_name="work", repo_relative_path="other/sample-app")

        first_name = build_report_filename(first)

        self.assertEqual(first_name, build_report_filename(first))
        self.assertNotEqual(first_name, build_report_filename(second))
        self.assertNotEqual(first_name, build_report_filename(nested))
        self.assertRegex(first_name, r"^work--team--sample-app--[0-9a-f]{16}\.md$")

    def test_posix_backslash_and_path_separator_have_distinct_identities(self):
        slash = _base_report(repo_relative_path="team/app")
        backslash = _base_report(repo_relative_path=r"team\app")

        self.assertNotEqual(
            build_report_filename(slash),
            build_report_filename(backslash),
        )

    def test_metadata_and_file_paths_cannot_break_markdown_structure(self):
        report = _base_report(
            repo_relative_path="team\n# injected",
            branch="main\x1b[31m",
            author_names=["**admin**"],
            commits=[{
                "hash": "abcdef123456",
                "date": "2026-06-28 10:30:00 +0900",
                "subject": "**bold**\n## injected",
                "files_changed": 1,
                "insertions": 1,
                "deletions": 0,
                "diff": "",
            }],
            untracked_files=["bad\n## heading```"],
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertNotIn("\n## injected", markdown)
        self.assertNotIn("\n## heading", markdown)
        self.assertNotIn("\x1b", markdown)
        self.assertIn(r"main\x1b[31m", markdown)
        self.assertIn(r"\# injected", markdown)
        self.assertIn(r"\*\*admin\*\*", markdown)

    def test_surrogateescaped_identity_is_hashable_and_renderable(self):
        report = _base_report(repo_relative_path="bad\udcffname")

        filename = build_report_filename(report)
        markdown = render_markdown(report, "2026-06-28")

        self.assertRegex(filename, r"^work--bad-name--[0-9a-f]{16}\.md$")
        self.assertRegex(
            markdown.splitlines()[1],
            r"^<!-- daily-code-learn-report:v1:[0-9a-f]{64} -->$",
        )
        self.assertIn(r"bad\xffname", markdown)
        markdown.encode("utf-8")

    def test_write_report_does_not_overwrite_same_basename_from_other_roots(self):
        with tempfile.TemporaryDirectory() as output_dir:
            first = _base_report(root_name="work", repo_relative_path="sample-app")
            second = _base_report(root_name="personal", repo_relative_path="sample-app")

            first_path = write_report(first, "2026-06-28", output_dir)
            second_path = write_report(second, "2026-06-28", output_dir)

            self.assertNotEqual(first_path, second_path)
            self.assertTrue(os.path.exists(first_path))
            self.assertTrue(os.path.exists(second_path))
            self.assertEqual(
                stat.S_IMODE(os.stat(os.path.dirname(first_path)).st_mode),
                0o700,
            )
            self.assertEqual(stat.S_IMODE(os.stat(first_path).st_mode), 0o600)
            report_dir = os.path.dirname(first_path)
            self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(report_dir)))

    def test_write_report_refuses_to_replace_an_unowned_file(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report = _base_report()
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            file_path = os.path.join(report_dir, build_report_filename(report))
            with open(file_path, "w", encoding="utf-8") as file:
                file.write("# Personal notes\nkeep me\n")

            with self.assertRaises(FileExistsError):
                write_report(report, "2026-06-28", output_dir)

            with open(file_path, "r", encoding="utf-8") as file:
                self.assertEqual(file.read(), "# Personal notes\nkeep me\n")

    def test_write_report_refuses_a_symlink_date_directory(self):
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as outside_dir:
            date_dir = os.path.join(output_dir, "2026-06-28")
            try:
                os.symlink(outside_dir, date_dir, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            with self.assertRaises(OSError):
                write_report(_base_report(), "2026-06-28", output_dir)

            self.assertEqual(os.listdir(outside_dir), [])

    def test_write_report_does_not_escape_if_date_directory_is_swapped(self):
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as outside_dir:
            date_dir = os.path.join(output_dir, "2026-06-28")
            moved_dir = os.path.join(output_dir, "moved-date")
            real_create = renderer._create_temporary_report

            def swap_then_create(directory_fd):
                os.rename(date_dir, moved_dir)
                os.symlink(outside_dir, date_dir, target_is_directory=True)
                return real_create(directory_fd)

            with patch.object(
                renderer,
                "_create_temporary_report",
                side_effect=swap_then_create,
            ), self.assertRaises(OSError):
                write_report(_base_report(), "2026-06-28", output_dir)
            if not os.path.islink(date_dir):
                self.skipTest("directory symlinks unavailable")

            self.assertEqual(os.listdir(outside_dir), [])
            self.assertFalse(any(name.endswith(".tmp") for name in os.listdir(moved_dir)))
            self.assertFalse(any(name.endswith(".md") for name in os.listdir(moved_dir)))

    def test_write_report_can_atomically_replace_the_same_identity(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report = _base_report(branch="before")
            first_path = write_report(report, "2026-06-28", output_dir)
            report["branch"] = "after"

            second_path = write_report(report, "2026-06-28", output_dir)

            self.assertEqual(first_path, second_path)
            with open(second_path, "r", encoding="utf-8") as file:
                content = file.read()
            self.assertIn("- 브랜치: `after`", content)
            self.assertNotIn("- 브랜치: `before`", content)

    def test_write_report_fails_clearly_without_hard_link_support(self):
        with tempfile.TemporaryDirectory() as output_dir:
            with patch.object(
                renderer.os,
                "link",
                side_effect=OSError(errno.EOPNOTSUPP, "not supported"),
            ), self.assertRaisesRegex(OSError, "하드 링크"):
                write_report(_base_report(), "2026-06-28", output_dir)

            report_dir = os.path.join(output_dir, "2026-06-28")
            self.assertFalse(any(
                name.endswith(".tmp") for name in os.listdir(report_dir)
            ))

    def test_write_report_stops_when_recovery_artifact_exists(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.mkdir(report_dir, mode=0o700)
            recovery_name = ".report-" + ("a" * 24) + ".tmp"
            recovery_path = os.path.join(report_dir, recovery_name)
            with open(recovery_path, "w", encoding="utf-8") as file:
                file.write("interrupted publication")

            with self.assertRaisesRegex(FileExistsError, "복구 파일"):
                write_report(_base_report(), "2026-06-28", output_dir)

            self.assertTrue(os.path.exists(recovery_path))
            self.assertFalse(any(
                name.endswith(".md") for name in os.listdir(report_dir)
            ))

    def test_ambiguous_replace_failure_preserves_previous_report(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report = _base_report(branch="before")
            file_path = write_report(report, "2026-06-28", output_dir)
            report["branch"] = "after"

            with patch.object(
                renderer.os,
                "replace",
                side_effect=OSError(errno.EIO, "ambiguous failure"),
            ), self.assertRaises(OSError):
                write_report(report, "2026-06-28", output_dir)

            with open(file_path, "r", encoding="utf-8") as file:
                self.assertIn("- 브랜치: `before`", file.read())
            recovery_names = [
                name
                for name in os.listdir(os.path.dirname(file_path))
                if name.startswith(".previous-report-")
            ]
            self.assertEqual(len(recovery_names), 1)

    def test_written_path_carries_artifact_identity_for_notification(self):
        with tempfile.TemporaryDirectory() as output_dir:
            path = write_report(
                _base_report(),
                "2026-06-28",
                output_dir,
            )

            self.assertIsInstance(path, str)
            self.assertEqual(len(path.report_directory_identity), 2)
            self.assertEqual(len(path.report_file_identity), 2)
            self.assertRegex(path.report_content_sha256, r"^[0-9a-f]{64}$")

    def test_new_report_refuses_a_target_created_after_validation(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report = _base_report()
            report_dir = os.path.join(output_dir, "2026-06-28")
            file_name = build_report_filename(report)
            file_path = os.path.join(report_dir, file_name)
            real_link = renderer.os.link
            inserted = False

            def insert_before_publish(source, destination, *args, **kwargs):
                nonlocal inserted
                if (
                    not inserted
                    and source.startswith(".report-")
                    and destination == file_name
                ):
                    inserted = True
                    with open(file_path, "w", encoding="utf-8") as file:
                        file.write("foreign content")
                return real_link(source, destination, *args, **kwargs)

            with patch.object(
                renderer.os,
                "link",
                side_effect=insert_before_publish,
            ), self.assertRaises(FileExistsError):
                write_report(report, "2026-06-28", output_dir)

            with open(file_path, "r", encoding="utf-8") as file:
                self.assertEqual(file.read(), "foreign content")
            self.assertFalse(
                any(name.startswith(".report-") for name in os.listdir(report_dir))
            )

    def test_existing_report_refuses_a_target_swapped_before_backup(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report = _base_report(branch="before")
            file_path = write_report(report, "2026-06-28", output_dir)
            file_name = os.path.basename(file_path)
            report["branch"] = "after"
            real_link = renderer.os.link
            swapped = False

            def swap_before_backup(source, destination, *args, **kwargs):
                nonlocal swapped
                if (
                    not swapped
                    and source == file_name
                    and destination.startswith(".previous-report-")
                ):
                    swapped = True
                    os.unlink(file_path)
                    with open(file_path, "w", encoding="utf-8") as file:
                        file.write("foreign content")
                return real_link(source, destination, *args, **kwargs)

            with patch.object(
                renderer.os,
                "link",
                side_effect=swap_before_backup,
            ), self.assertRaises(FileExistsError):
                write_report(report, "2026-06-28", output_dir)

            with open(file_path, "r", encoding="utf-8") as file:
                self.assertEqual(file.read(), "foreign content")
            self.assertFalse(any(
                name.startswith(".previous-report-")
                for name in os.listdir(os.path.dirname(file_path))
            ))

    def test_write_report_rejects_group_writable_date_directory(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir, mode=0o770)
            os.chmod(report_dir, 0o770)

            with self.assertRaises(PermissionError):
                write_report(_base_report(), "2026-06-28", output_dir)

    def test_write_report_rechecks_permissions_after_acquiring_lock(self):
        with tempfile.TemporaryDirectory() as output_dir:
            def widen_permissions(directory_fd, operation):
                if operation == renderer.fcntl.LOCK_EX:
                    os.fchmod(directory_fd, 0o770)

            with patch.object(
                renderer.fcntl,
                "flock",
                side_effect=widen_permissions,
            ), self.assertRaises(PermissionError):
                write_report(_base_report(), "2026-06-28", output_dir)

            report_dir = os.path.join(output_dir, "2026-06-28")
            self.assertFalse(any(
                name.endswith(".tmp") or name.endswith(".md")
                for name in os.listdir(report_dir)
            ))

    def test_write_report_fsyncs_new_output_ancestors_and_date_parent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = os.path.join(tmp_dir, "nested", "reports")
            observed_paths = []
            real_fsync_directory_path = renderer._fsync_directory_path

            def record_fsync(path):
                observed_paths.append(os.path.abspath(path))
                real_fsync_directory_path(path)

            with patch.object(
                renderer,
                "_fsync_directory_path",
                side_effect=record_fsync,
            ):
                write_report(_base_report(), "2026-06-28", output_dir)

            self.assertTrue({
                os.path.abspath(tmp_dir),
                os.path.abspath(os.path.join(tmp_dir, "nested")),
                os.path.abspath(output_dir),
            }.issubset(observed_paths))

    def test_diff_controls_are_visible_text_not_terminal_commands(self):
        report = _base_report(
            staged_files=["control.txt"],
            staged_diff=(
                "diff --git a/control.txt b/control.txt\n"
                "+tab\tkept\x1b[2J\rreturn\x85next\udcff"
            ),
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertNotIn("\x1b", markdown)
        self.assertNotIn("\r", markdown)
        self.assertNotIn("\x85", markdown)
        self.assertIn("\t", markdown)
        self.assertIn(r"\x1b[2J\rreturn\x85next\xff", markdown)
        markdown.encode("utf-8")

    def test_diff_fence_expands_when_content_contains_backticks(self):
        report = _base_report(
            staged_files=["README.md"],
            staged_diff="diff --git a/README.md b/README.md\n+```python\n+value\n+```",
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertIn("````diff", markdown)
        self.assertIn("\n````\n", markdown)


if __name__ == "__main__":
    unittest.main()
