import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lib.git_commands import (
    MAX_PATHS_PER_DIFF_COMMAND,
    MAX_PATHSPEC_BYTES_PER_DIFF_COMMAND,
    GitCommandError,
    _chunk_path_groups,
    _filter_diff_excludes,
    _filter_excludes,
    _limited_filtered_diff,
    _run_git,
    _run_git_diff,
    _sanitize_error,
    get_commit_diff_limited,
    get_commit_dates_by_author,
    get_commits_by_author,
    get_current_branch,
    get_staged_diff_limited,
    get_staged_files,
)


class GitCommandFilterTests(unittest.TestCase):
    def test_git_error_sanitizer_redacts_url_credentials_and_tokens(self):
        error = (
            "fatal: https://user:password@example.com/repo.git?"
            "access_token=secret-value&ref=main"
        )

        sanitized = _sanitize_error(error)

        self.assertNotIn("user:password", sanitized)
        self.assertNotIn("secret-value", sanitized)
        self.assertIn("https://***@example.com", sanitized)
        self.assertIn("access_token=***", sanitized)

    def test_git_error_sanitizer_escapes_terminal_controls(self):
        sanitized = _sanitize_error("fatal:\x1b[2Jline\r\nnext\x80\udcff")

        self.assertNotIn("\x1b", sanitized)
        self.assertNotIn("\r", sanitized)
        self.assertNotIn("\n", sanitized)
        self.assertNotIn("\x80", sanitized)
        self.assertNotIn("\udcff", sanitized)
        self.assertIn(r"\x1b[2J", sanitized)
        self.assertIn(r"\r\n", sanitized)
        self.assertIn(r"\x80\xff", sanitized)

    def test_pathspec_chunks_are_bounded_without_splitting_rename_pairs(self):
        groups = [[f"path-{index}.txt"] for index in range(255)]
        groups.append(["old-name.txt", "new-name.txt"])

        chunks = list(_chunk_path_groups(groups))

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[-1], ["old-name.txt", "new-name.txt"])
        for chunk in chunks:
            self.assertLessEqual(len(chunk), MAX_PATHS_PER_DIFF_COMMAND)
            self.assertLessEqual(
                sum(len(os.fsencode(path)) + 1 for path in chunk),
                MAX_PATHSPEC_BYTES_PER_DIFF_COMMAND,
            )

        byte_heavy_groups = [
            [f"{index:02d}-" + ("x" * 1000)]
            for index in range(40)
        ]
        byte_bounded_chunks = list(_chunk_path_groups(byte_heavy_groups))
        self.assertGreater(len(byte_bounded_chunks), 1)
        for chunk in byte_bounded_chunks:
            self.assertLessEqual(
                sum(len(os.fsencode(path)) + 1 for path in chunk),
                MAX_PATHSPEC_BYTES_PER_DIFF_COMMAND,
            )

    def test_filtered_diff_uses_multiple_bounded_git_commands(self):
        groups = [[f"src/file-{index:04d}.txt"] for index in range(600)]
        observed_args = []

        def fake_diff(_repo_path, args, *_args, **_kwargs):
            observed_args.append(args)
            return "", False, 0

        with patch(
            "lib.git_commands._safe_changed_path_groups",
            return_value=groups,
        ), patch("lib.git_commands._run_git_diff", side_effect=fake_diff):
            result = _limited_filtered_diff(
                "/repo",
                ["diff", "--cached"],
                ["diff", "--cached", "--name-status", "-z"],
                [],
                max_lines=0,
                include_sensitive_files=False,
                max_bytes=0,
            )

        self.assertEqual(result, ("", False, 0))
        self.assertGreater(len(observed_args), 1)
        for args in observed_args:
            pathspecs = args[args.index("--") + 1:]
            self.assertLessEqual(len(pathspecs), MAX_PATHS_PER_DIFF_COMMAND)
            self.assertLessEqual(
                sum(len(os.fsencode(path)) + 1 for path in pathspecs),
                MAX_PATHSPEC_BYTES_PER_DIFF_COMMAND,
            )

    def test_filter_excludes_supports_segment_and_glob_patterns(self):
        files = [
            "src/app.py",
            "dist/app.js",
            "src/distribution/app.js",
            "src/rebuild.py",
            "nested/foo.lock",
            "package-lock.json",
            "src/keep.ts",
        ]

        self.assertEqual(
            _filter_excludes(files, ["dist", "*.lock", "package-lock.json"]),
            [
                "src/app.py",
                "src/distribution/app.js",
                "src/rebuild.py",
                "src/keep.ts",
            ],
        )

    @unittest.skipIf(os.sep == "\\", "POSIX filename semantics only")
    def test_filter_excludes_keeps_backslash_distinct_from_path_separator(self):
        files = ["folder/file.txt", "folder\\file.txt"]

        self.assertEqual(
            _filter_excludes(files, ["folder/file.txt"]),
            ["folder\\file.txt"],
        )
        self.assertEqual(
            _filter_excludes(files, ["folder\\file.txt"]),
            ["folder/file.txt"],
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

    def test_sensitive_paths_are_excluded_by_default_with_safe_templates(self):
        files = [
            ".env",
            "config/.env.production",
            ".env.example",
            "keys/id_ed25519",
            "certs/client.pem",
            "config/credentials.yaml",
            "config/service-account.yml",
            "src/app.py",
        ]

        self.assertEqual(
            _filter_excludes(files, []),
            [".env.example", "src/app.py"],
        )
        self.assertEqual(
            _filter_excludes(files, [], include_sensitive_files=True),
            files,
        )


class GitCommandIntegrationTests(unittest.TestCase):
    def _init_repo(self, directory):
        subprocess.run(
            ["git", "init"], cwd=directory, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Default User"],
            cwd=directory,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "default@example.com"],
            cwd=directory,
            check=True,
            capture_output=True,
        )

    def _commit(self, repo_path, subject, email, author_date, committer_date):
        file_path = os.path.join(repo_path, "history.txt")
        with open(file_path, "a", encoding="utf-8") as file:
            file.write(subject + "\n")
        subprocess.run(
            ["git", "add", "history.txt"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        env = os.environ.copy()
        env.update({
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": email,
            "GIT_AUTHOR_DATE": author_date,
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": email,
            "GIT_COMMITTER_DATE": committer_date,
        })
        subprocess.run(
            ["git", "commit", "-m", subject],
            cwd=repo_path,
            check=True,
            capture_output=True,
            env=env,
        )

    def test_committer_date_and_multiple_emails_are_consistent_and_sorted(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            self._commit(
                repo_path,
                "first | subject",
                "tester+one@example.com",
                "2020-01-02T10:00:00+0900",
                "2026-06-28T10:00:00+0900",
            )
            self._commit(
                repo_path,
                "second",
                "tester.two@example.com",
                "2021-01-02T11:00:00+0900",
                "2026-06-28T11:00:00+0900",
            )

            commits = get_commits_by_author(
                repo_path,
                ["tester+one@example.com", "tester.two@example.com"],
                "2026-06-28",
            )

            self.assertEqual([commit["subject"] for commit in commits], ["second", "first | subject"])
            self.assertTrue(all(commit["date"].startswith("2026-06-28") for commit in commits))
            self.assertTrue(all(commit["files_changed"] == 1 for commit in commits))
            self.assertTrue(all(commit["insertions"] == 1 for commit in commits))

    def test_detached_head_has_an_explicit_branch_label(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            self._commit(
                repo_path,
                "detached",
                "tester@example.com",
                "2026-06-28T10:00:00+0000",
                "2026-06-28T10:00:00+0000",
            )
            subprocess.run(
                ["git", "checkout", "--detach", "HEAD"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            self.assertEqual(get_current_branch(repo_path), "(detached HEAD)")

    def test_commits_are_sorted_by_committer_time_despite_topology_clock_skew(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            self._commit(
                repo_path,
                "chronologically newer parent",
                "tester@example.com",
                "2026-06-28T11:00:00+0000",
                "2026-06-28T11:00:00+0000",
            )
            self._commit(
                repo_path,
                "clock-skewed child",
                "tester@example.com",
                "2026-06-28T10:00:00+0000",
                "2026-06-28T10:00:00+0000",
            )

            commits = get_commits_by_author(
                repo_path,
                ["tester@example.com"],
                "2026-06-28",
            )

            self.assertEqual(
                [commit["subject"] for commit in commits],
                ["chronologically newer parent", "clock-skewed child"],
            )

    def test_commits_are_sorted_by_epoch_across_dst_fallback(self):
        with tempfile.TemporaryDirectory() as repo_path, patch.dict(
            os.environ,
            {"TZ": "Europe/Berlin"},
        ):
            self._init_repo(repo_path)
            self._commit(
                repo_path,
                "older repeated wall time",
                "tester@example.com",
                "2026-10-25T02:30:00+0200",
                "2026-10-25T02:30:00+0200",
            )
            self._commit(
                repo_path,
                "newer repeated wall time",
                "tester@example.com",
                "2026-10-25T02:30:00+0100",
                "2026-10-25T02:30:00+0100",
            )

            commits = get_commits_by_author(
                repo_path,
                ["tester@example.com"],
                "2026-10-25",
            )

            self.assertEqual(
                [commit["subject"] for commit in commits],
                ["newer repeated wall time", "older repeated wall time"],
            )

    def test_diff_marker_can_show_the_full_limit_for_a_later_chunk(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            self._commit(
                repo_path,
                "marker limit",
                "tester@example.com",
                "2026-06-28T10:00:00+0000",
                "2026-06-28T10:00:00+0000",
            )

            diff, truncated, _omitted = _run_git_diff(
                repo_path,
                ["show", "--format=", "--no-color", "HEAD"],
                [],
                max_lines=1,
                marker_max_lines=1793,
            )

            self.assertTrue(truncated)
            self.assertIn("최대 1793줄 이후 diff 생략", diff)

    def test_date_walk_does_not_stop_at_an_older_child_commit(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            self._commit(
                repo_path,
                "target-day parent",
                "tester@example.com",
                "2026-06-28T11:00:00+0000",
                "2026-06-28T11:00:00+0000",
            )
            self._commit(
                repo_path,
                "older clock-skewed child",
                "tester@example.com",
                "2026-06-27T10:00:00+0000",
                "2026-06-27T10:00:00+0000",
            )

            commits = get_commits_by_author(
                repo_path,
                ["tester@example.com"],
                "2026-06-28",
            )
            dates = get_commit_dates_by_author(
                repo_path,
                ["tester@example.com"],
                "2026-06-28",
                "2026-06-28",
            )

            self.assertEqual(
                [commit["subject"] for commit in commits],
                ["target-day parent"],
            )
            self.assertEqual(dates, {"2026-06-28": 1})

    def test_author_email_with_field_delimiter_is_parsed_consistently(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            email = "tester|alias@example.com"
            self._commit(
                repo_path,
                "delimiter email",
                email,
                "2026-06-28T10:00:00+0000",
                "2026-06-28T10:00:00+0000",
            )

            commits = get_commits_by_author(
                repo_path,
                [email],
                "2026-06-28",
            )
            dates = get_commit_dates_by_author(
                repo_path,
                [email],
                "2026-06-28",
                "2026-06-28",
            )

            self.assertEqual(
                [commit["subject"] for commit in commits],
                ["delimiter email"],
            )
            self.assertEqual(dates, {"2026-06-28": 1})

    def test_streamed_diff_enforces_retained_line_limit(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            self._commit(
                repo_path,
                "large diff",
                "tester@example.com",
                "2026-06-28T10:00:00+0900",
                "2026-06-28T10:00:00+0900",
            )
            commit_hash = _run_git(repo_path, ["rev-parse", "HEAD"])

            diff, truncated, omitted = get_commit_diff_limited(
                repo_path,
                commit_hash,
                [],
                max_lines=4,
            )

            self.assertTrue(truncated)
            self.assertIsNone(omitted)
            self.assertEqual(len(diff.splitlines()), 5)
            self.assertIn("최대 4줄 이후 diff 생략", diff)

    def test_streamed_diff_stops_reading_after_the_limit(self):
        class FakeStdout:
            def __init__(self):
                self.read_count = 0
                self.closed = False

            def readline(self, _size=-1):
                if self.read_count >= 100:
                    return ""
                index = self.read_count
                self.read_count += 1
                return f"line {index}\n"

            def close(self):
                self.closed = True

        class FakeProcess:
            def __init__(self):
                self.stdout = FakeStdout()
                self.terminated = False

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.terminated = True

            def wait(self):
                return -15 if self.terminated else 0

        process = FakeProcess()
        with patch("lib.git_commands.subprocess.Popen", return_value=process):
            diff, truncated, omitted = _run_git_diff(
                "/repo",
                ["diff"],
                [],
                max_lines=3,
                include_sensitive_files=True,
            )

        self.assertTrue(process.terminated)
        self.assertTrue(process.stdout.closed)
        self.assertEqual(process.stdout.read_count, 4)
        self.assertTrue(truncated)
        self.assertIsNone(omitted)
        self.assertEqual(len(diff.splitlines()), 4)

    def test_streamed_diff_bounds_a_single_line_by_bytes(self):
        class FakeStdout:
            def __init__(self):
                self.remaining = 10 * 1024 * 1024
                self.read_sizes = []
                self.closed = False

            def readline(self, size=-1):
                self.read_sizes.append(size)
                if self.remaining == 0:
                    return ""
                amount = min(size, self.remaining)
                self.remaining -= amount
                return "x" * amount

            def close(self):
                self.closed = True

        class FakeProcess:
            def __init__(self):
                self.stdout = FakeStdout()
                self.terminated = False

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.terminated = True

            def wait(self):
                return -15 if self.terminated else 0

        process = FakeProcess()
        with patch("lib.git_commands.subprocess.Popen", return_value=process):
            diff, truncated, omitted = _run_git_diff(
                "/repo",
                ["diff"],
                [],
                max_lines=10,
                include_sensitive_files=True,
                max_bytes=1024,
            )

        payload, marker = diff.split("\n", 1)
        self.assertEqual(len(payload.encode("utf-8")), 1024)
        self.assertIn("1024바이트", marker)
        self.assertEqual(process.stdout.read_sizes, [64 * 1024])
        self.assertTrue(process.terminated)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(truncated)
        self.assertIsNone(omitted)

    def test_sensitive_rename_with_spaces_is_removed_as_one_change(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            source_dir = os.path.join(repo_path, "secret folder")
            os.makedirs(source_dir)
            source_path = os.path.join(source_dir, ".env")
            with open(source_path, "w", encoding="utf-8") as file:
                file.write("TOKEN=do-not-report\n")
            subprocess.run(
                ["git", "add", "secret folder/.env"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "add secret"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "mv", "secret folder/.env", "safe.txt"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            diff, truncated, omitted = get_staged_diff_limited(
                repo_path,
                [],
                max_lines=100,
            )

            self.assertEqual(diff, "")
            self.assertFalse(truncated)
            self.assertEqual(omitted, 0)

    def test_git_magic_looking_filename_is_treated_as_a_literal_path(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            unusual_name = ":(exclude)*"
            with open(os.path.join(repo_path, unusual_name), "w", encoding="utf-8") as file:
                file.write("literal pathspec\n")
            subprocess.run(
                ["git", "--literal-pathspecs", "add", unusual_name],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            diff, truncated, omitted = get_staged_diff_limited(
                repo_path,
                [],
                max_lines=100,
            )

            self.assertIn(":(exclude)*", diff)
            self.assertIn("+literal pathspec", diff)
            self.assertFalse(truncated)
            self.assertEqual(omitted, 0)

    def test_nul_delimited_file_list_preserves_newlines_in_paths(self):
        with tempfile.TemporaryDirectory() as repo_path:
            self._init_repo(repo_path)
            unusual_name = "line\nbreak.txt"
            with open(os.path.join(repo_path, unusual_name), "w", encoding="utf-8") as file:
                file.write("value\n")
            subprocess.run(
                ["git", "add", unusual_name],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            self.assertEqual(get_staged_files(repo_path, []), [unusual_name])

    @unittest.skipIf(os.name == "nt", "surrogateescape filename semantics are POSIX-only")
    def test_invalid_filename_bytes_are_preserved_and_diff_is_utf8_safe(self):
        filename = b"invalid-\xff.txt"
        decoded_filename = os.fsdecode(filename)
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{decoded_filename}\0",
            stderr="",
        )
        with patch(
            "lib.git_commands.subprocess.run",
            return_value=completed,
        ) as run:
            files = get_staged_files("/repo", [])

        self.assertEqual([os.fsencode(path) for path in files], [filename])
        self.assertEqual(run.call_args.kwargs["errors"], "surrogateescape")

        class FakeStdout:
            def __init__(self):
                self.fragments = [
                    f"diff --git a/{decoded_filename} b/{decoded_filename}\n",
                    "+value\n",
                ]

            def readline(self, _size=-1):
                return self.fragments.pop(0) if self.fragments else ""

            def close(self):
                pass

        class FakeProcess:
            def __init__(self):
                self.stdout = FakeStdout()

            def terminate(self):
                pass

            def kill(self):
                pass

            def wait(self):
                return 0

        with patch(
            "lib.git_commands.subprocess.Popen",
            return_value=FakeProcess(),
        ) as popen:
            diff, truncated, omitted = _run_git_diff(
                "/repo",
                ["diff"],
                [],
                max_lines=100,
                include_sensitive_files=True,
            )

        self.assertEqual(popen.call_args.kwargs["errors"], "surrogateescape")
        self.assertIn(r"invalid-\xff.txt", diff)
        self.assertFalse(
            any(0xD800 <= ord(character) <= 0xDFFF for character in diff)
        )
        diff.encode("utf-8")
        self.assertFalse(truncated)
        self.assertEqual(omitted, 0)

    def test_git_failures_raise_user_facing_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(GitCommandError) as context:
                _run_git(directory, ["status", "--short"])

            self.assertIn("git status 실패", str(context.exception))


if __name__ == "__main__":
    unittest.main()
