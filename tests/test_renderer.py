import unittest

from lib.renderer import render_markdown


def _base_report(**overrides):
    report = {
        "project_name": "sample-app",
        "repo_path": "/workspace/sample-app",
        "branch": "main",
        "author_name": "Sample",
        "author_email": "sample@example.com",
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

        self.assertIn("## 오늘 작업 요약", markdown)
        self.assertIn("- Staged: 1 files", markdown)
        self.assertIn("### Staged", markdown)
        self.assertIn("- src/app.py", markdown)
        self.assertIn("<summary>staged diff 보기</summary>", markdown)
        self.assertIn("+print('hello')", markdown)

    def test_renders_untracked_file_list_without_diff(self):
        report = _base_report(
            untracked_files=["src/draft.py"],
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertIn("- Untracked: 1 files", markdown)
        self.assertIn("### Untracked", markdown)
        self.assertIn("- src/draft.py", markdown)
        self.assertNotIn("<summary>untracked diff 보기</summary>", markdown)

    def test_renders_file_list_only_when_uncommitted_diff_is_disabled(self):
        report = _base_report(
            include_uncommitted_diff=False,
            unstaged_files=["src/app.py"],
            unstaged_diff="diff --git a/src/app.py b/src/app.py",
        )

        markdown = render_markdown(report, "2026-06-28")

        self.assertIn("### Unstaged", markdown)
        self.assertIn("- src/app.py", markdown)
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


if __name__ == "__main__":
    unittest.main()
