import os
import tempfile
import unittest
from unittest.mock import patch

from lib.scanner import scan_repos
from lib.parallel import run_parallel_over_repos


class ScannerTests(unittest.TestCase):
    def _make_repo_marker(self, path, worktree=False):
        os.makedirs(path, exist_ok=True)
        git_entry = os.path.join(path, ".git")
        if worktree:
            with open(git_entry, "w", encoding="utf-8") as file:
                file.write("gitdir: /tmp/example\n")
        else:
            os.makedirs(git_entry)

    def test_depth_is_configurable_and_defaults_to_direct_children(self):
        with tempfile.TemporaryDirectory() as root_path:
            direct = os.path.join(root_path, "direct")
            nested = os.path.join(root_path, "group", "nested")
            self._make_repo_marker(direct)
            self._make_repo_marker(nested)

            self.assertEqual(scan_repos(root_path), [direct])
            self.assertEqual(scan_repos(root_path, max_depth=2), [direct, nested])

    def test_git_file_is_recognized_as_worktree(self):
        with tempfile.TemporaryDirectory() as root_path:
            worktree = os.path.join(root_path, "linked-worktree")
            self._make_repo_marker(worktree, worktree=True)

            self.assertEqual(scan_repos(root_path), [worktree])

    def test_scanning_stops_after_repository_is_found(self):
        with tempfile.TemporaryDirectory() as root_path:
            outer = os.path.join(root_path, "outer")
            nested = os.path.join(outer, "vendor", "nested")
            self._make_repo_marker(outer)
            self._make_repo_marker(nested)

            self.assertEqual(scan_repos(root_path, max_depth=5), [outer])

    def test_root_itself_can_be_a_repository(self):
        with tempfile.TemporaryDirectory() as root_path:
            self._make_repo_marker(root_path)

            self.assertEqual(scan_repos(root_path), [os.path.abspath(root_path)])

    def test_symlink_alias_does_not_duplicate_the_same_repository(self):
        with tempfile.TemporaryDirectory() as root_path:
            repository = os.path.join(root_path, "repository")
            alias = os.path.join(root_path, "alias")
            self._make_repo_marker(repository)
            try:
                os.symlink(repository, alias, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            self.assertEqual(len(scan_repos(root_path)), 1)
            self.assertEqual(
                os.path.realpath(scan_repos(root_path)[0]),
                os.path.realpath(repository),
            )

    def test_parallel_runner_rejects_cross_root_aliases_of_same_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = os.path.join(directory, "repository")
            first_root = os.path.join(directory, "first")
            second_root = os.path.join(directory, "second")
            os.makedirs(first_root)
            os.makedirs(second_root)
            self._make_repo_marker(repository)
            try:
                os.symlink(repository, os.path.join(first_root, "app"))
                os.symlink(repository, os.path.join(second_root, "app"))
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")

            processed = []
            results = run_parallel_over_repos(
                {"roots": [
                    {"name": "first", "path": first_root},
                    {"name": "second", "path": second_root},
                ]},
                lambda repo_path, _root, progress: (
                    processed.append(repo_path),
                    progress.complete_one(),
                    repo_path,
                )[-1],
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(len(processed), 1)
            self.assertEqual(len(results.errors), 1)
            self.assertIn("여러 root", results.errors[0]["message"])

    def test_parallel_runner_rejects_case_aliases_on_case_insensitive_filesystems(self):
        with tempfile.TemporaryDirectory() as directory:
            root_path = os.path.join(directory, "CaseRoot")
            alias_path = os.path.join(directory, "caseroot")
            repository = os.path.join(root_path, "Repository")
            self._make_repo_marker(repository)
            if not os.path.isdir(alias_path):
                self.skipTest("case-sensitive filesystem")
            if not os.path.samefile(root_path, alias_path):
                self.skipTest("paths are not filesystem aliases")

            processed = []
            results = run_parallel_over_repos(
                {"roots": [
                    {"name": "first", "path": root_path},
                    {"name": "second", "path": alias_path},
                ]},
                lambda repo_path, _root, progress: (
                    processed.append(repo_path),
                    progress.complete_one(),
                    repo_path,
                )[-1],
            )

            self.assertEqual(len(processed), 1)
            self.assertEqual(len(results.errors), 1)
            self.assertIn("여러 root", results.errors[0]["message"])

    def test_parallel_runner_isolates_repository_failures(self):
        with tempfile.TemporaryDirectory() as root_path:
            repo_path = os.path.join(root_path, "group", "broken")
            self._make_repo_marker(repo_path)
            config = {
                "roots": [{"name": "work", "path": root_path, "maxDepth": 2}]
            }

            def fail(_repo_path, _root, _progress):
                raise RuntimeError("broken repository")

            results = run_parallel_over_repos(config, fail)

            self.assertEqual(results, [])
            self.assertEqual(len(results.errors), 1)
            self.assertEqual(results.errors[0]["repo_path"], repo_path)
            self.assertEqual(
                results.errors[0]["repo_relative_path"], "group/broken"
            )
            self.assertIn("broken repository", results.errors[0]["message"])

    def test_parallel_runner_preserves_other_roots_when_discovery_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            failed_root = os.path.join(directory, "failed")
            healthy_root = os.path.join(directory, "healthy")
            os.makedirs(failed_root)
            os.makedirs(healthy_root)
            healthy_repo = os.path.join(healthy_root, "app")
            self._make_repo_marker(healthy_repo)
            config = {
                "roots": [
                    {"name": "failed", "path": failed_root},
                    {"name": "healthy", "path": healthy_root},
                ]
            }

            def scan(root_path, max_depth):
                if root_path == failed_root:
                    raise PermissionError("denied")
                return [healthy_repo]

            with patch("lib.parallel.scan_repos", side_effect=scan):
                results = run_parallel_over_repos(
                    config,
                    lambda repo_path, _root, progress: (
                        progress.complete_one(), repo_path
                    )[1],
                )

            self.assertEqual(results, [healthy_repo])
            self.assertEqual(len(results.errors), 1)
            self.assertEqual(results.errors[0]["repo_relative_path"], "failed")
            self.assertIn("저장소 탐색 실패", results.errors[0]["message"])

    def test_parallel_runner_reports_root_removed_after_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_root = os.path.join(directory, "removed")
            results = run_parallel_over_repos(
                {"roots": [{"name": "work", "path": missing_root}]},
                lambda *_args: None,
            )

            self.assertEqual(results, [])
            self.assertEqual(len(results.errors), 1)
            self.assertEqual(results.errors[0]["repo_relative_path"], "removed")
            self.assertIn("root 경로가 없습니다", results.errors[0]["message"])


if __name__ == "__main__":
    unittest.main()
