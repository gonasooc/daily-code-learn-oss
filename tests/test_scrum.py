import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from lib import scrum
from lib.config import ConfigError
from lib.git_commands import GitCommandError


class SubjectTests(unittest.TestCase):
    def test_keeps_source_text_and_only_reads_metadata_before_comment(self):
        subject = "VD-123 #time 1h  30m #comment Fix `a_b` #time 2h and #comment examples"
        parsed = scrum.parse_subject(subject)
        self.assertEqual(parsed["subject"], subject)
        self.assertEqual(parsed["ticket"], "VD-123")
        self.assertEqual(parsed["time_text"], "1h  30m")
        self.assertEqual(parsed["minutes"], 90)
        self.assertEqual(parsed["comment"], "Fix `a_b` #time 2h and #comment examples")

    def test_comment_without_metadata_does_not_create_time(self):
        parsed = scrum.parse_subject("VD-5 #comment Explain #time 2h")
        self.assertIsNone(parsed["minutes"])
        self.assertIsNone(parsed["time_text"])
        self.assertEqual(parsed["comment"], "Explain #time 2h")

    def test_missing_and_unsupported_time_are_not_counted_as_zero(self):
        for subject, time_text in (("fix: things", None), ("VD-4 #time 1d #comment Work", "1d"),
                                   ("VD-4 #time 1.5h #comment Work", "1.5h"),
                                   ("VD-4 #time 1h 2d #comment Work", "1h 2d")):
            with self.subTest(subject=subject):
                parsed = scrum.parse_subject(subject)
                self.assertIsNone(parsed["minutes"])
                self.assertEqual(parsed["time_text"], time_text)

    def test_duration_without_comment_preserves_remaining_description(self):
        parsed = scrum.parse_subject("VD-12 #time 10m Fix the warning")
        self.assertEqual(parsed["comment"], "Fix the warning")
        self.assertEqual(parsed["minutes"], 10)
        self.assertEqual(scrum.parse_subject("Fix #timekeeper docs")["comment"], "Fix #timekeeper docs")
        self.assertIsNone(scrum.parse_subject("fix x#time 1h")["time_text"])

    def test_duplicate_time_markers_are_ambiguous(self):
        self.assertIsNone(scrum.parse_subject("VD-1 #time 1h #time 2h #comment Work")["minutes"])

    def test_git_subject_line_separators_survive_and_order_uses_epoch(self):
        output = ("old\0002026-09-25 01:45:00 +0100\000100\000tester@example.com\000Earlier\n"
                  "new\0002026-09-25 01:30:00 +0000\000200\000tester@example.com\000Keep\u2028separator")
        with patch.object(scrum, "_run_git", return_value=output):
            commits = scrum._range_commits("/test", ["tester@example.com"], "2026-09-25", "2026-09-28", 999)
        self.assertEqual([commit["hash"] for commit in commits], ["new", "old"])
        self.assertEqual(commits[0]["subject"], "Keep\u2028separator")


class ScrumIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "work"
        self.root.mkdir()
        self.config = {
            "roots": [{"name": "work_team", "path": str(self.root), "maxDepth": 3,
                       "authorNames": ["Tester"], "authorEmails": ["tester@example.com"]}],
            "outputDir": str(self.base / "custom-reports"), "exclude": [],
            "scrum": {"root": "work_team", "outputDir": str(self.base / "notes")},
        }
        self.now = datetime(2026, 9, 28, 9, 0).astimezone()  # Monday, local time

    def git(self, path, *args, env=None):
        return subprocess.run(["git", "-C", str(path), *args], check=True,
                              capture_output=True, text=True, env=env).stdout.strip()

    def repo(self, name="app"):
        path = self.root / name
        path.mkdir(parents=True)
        self.git(path, "init")
        return path

    def commit(self, path, subject, when, email="tester@example.com"):
        env = os.environ.copy()
        stamp = datetime.fromisoformat(when).astimezone().isoformat()
        env.update(GIT_AUTHOR_NAME="Tester", GIT_COMMITTER_NAME="Tester",
                   GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_EMAIL=email,
                   GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        self.git(path, "commit", "--allow-empty", "-m", subject, env=env)
        return self.git(path, "rev-parse", "HEAD")

    def collect(self, **kwargs):
        with redirect_stderr(io.StringIO()):
            return scrum.collect_scrum(self.config, now=self.now, **kwargs)

    def test_weekend_uses_live_commits_despite_absent_or_stale_reports(self):
        app = self.repo()
        self.commit(app, "VD-1 #time 1h #comment Friday morning", "2026-09-25T08:00:00")
        self.commit(app, "VD-2 #time 1h 30m #comment Friday afternoon", "2026-09-25T18:00:00")
        self.commit(app, "Version update 2.0.0", "2026-09-27T16:00:00")
        self.commit(app, "VD-3 #comment Monday start", "2026-09-28T08:00:00")
        self.commit(app, "VD-9 #time 10h #comment Future stamp", "2026-09-28T18:00:00")
        with patch.object(scrum, "fetch", wraps=scrum.fetch) as fetch_mock, \
                patch.object(scrum, "_run_git", wraps=scrum._run_git) as git_mock:
            absent = self.collect()
        self.assertEqual(fetch_mock.call_count, 1)
        self.assertEqual(len(git_mock.call_args_list), 1)
        self.assertNotIn("--shortstat", git_mock.call_args.args[1])
        self.assertFalse((self.base / "notes").exists())
        self.assertFalse((self.base / "custom-reports").exists())
        stale = self.base / "custom-reports" / "2026-09-27" / "work-old.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("# 2026-09-27 - work_team/app\nWIP only stale snapshot\n")
        after = self.collect()
        self.assertEqual(absent, after)
        self.assertEqual(after["previous_work_date"], "2026-09-25")
        self.assertEqual(after["totals"]["known_minutes"], 150)
        self.assertEqual(after["totals"]["commit_count"], 3)
        self.assertEqual(after["totals"]["untimed_count"], 1)
        self.assertEqual(stale.read_text(), "# 2026-09-27 - work_team/app\nWIP only stale snapshot\n")

    def test_wip_only_repository_deduplicates_paths_and_excludes_secrets(self):
        app = self.repo()
        (app / "src").mkdir()
        tracked = app / "src" / "app.py"
        tracked.write_text("staged\n")
        self.git(app, "add", "src/app.py")
        tracked.write_text("unstaged\n")
        (app / "draft.py").write_text("draft\n")
        (app / ".env").write_text("LOCAL_TEST_VALUE=example\n")
        result = self.collect()
        self.assertTrue(result["complete"])
        self.assertIsNone(result["previous_work_date"])
        self.assertEqual(result["totals"]["commit_count"], 0)
        self.assertEqual(result["totals"]["wip_file_count"], 2)
        self.assertEqual(result["projects"][0]["wip"], {
            "count": 2, "files": ["draft.py", "src/app.py"], "directories": [".", "src"]})

    def test_only_today_commits_are_valid_and_history_replay_excludes_wip(self):
        app = self.repo()
        self.commit(app, "VD-1 #time 15m #comment Today", "2026-09-28T08:00:00")
        (app / "draft").write_text("wip")
        current = self.collect()
        self.assertIsNone(current["previous_work_date"])
        self.assertEqual(current["totals"]["known_minutes"], 15)
        replay = self.collect(target_date="2026-09-27")
        self.assertEqual(replay["projects"], [])
        self.assertEqual(replay["totals"]["wip_file_count"], 0)

    def test_relative_identity_and_selected_root_are_preserved(self):
        for name in ("team-a/app", "team-b/app"):
            app = self.repo(name)
            self.commit(app, "VD-1 #time 10m #comment Update", "2026-09-25T18:00:00")
        self.config["roots"].append({"name": "personal", "path": str(self.base / "missing"),
                                      "authorNames": [], "authorEmails": []})
        self.config["roots"].extend([None, "unrelated invalid root"])
        result = self.collect()
        self.assertEqual([project["repository"] for project in result["projects"]],
                         ["work_team/team-a/app", "work_team/team-b/app"])
        self.assertEqual(result["totals"]["commit_count"], 2)
        self.assertTrue(result["complete"])

    def test_lookback_bound_and_author_filter(self):
        app = self.repo()
        self.commit(app, "VD-1 #time 1h #comment Older", "2026-09-24T12:00:00")
        self.commit(app, "VD-2 #time 2h #comment Other person", "2026-09-25T12:00:00", "other@example.com")
        result = self.collect(days=3)
        self.assertEqual(result["range_start"], "2026-09-25")
        self.assertEqual(result["projects"], [])
        self.assertIsNone(result["previous_work_date"])

    def test_hash_is_deduplicated_within_repository(self):
        app = self.repo()
        self.commit(app, "VD-1 #time 1h #comment Work", "2026-09-25T12:00:00")
        original = scrum._run_git
        def duplicate(path, args):
            output = original(path, args)
            return output + "\n" + output
        with patch.object(scrum, "_run_git", side_effect=duplicate):
            result = self.collect()
        self.assertEqual(result["totals"]["commit_count"], 1)
        self.assertEqual(result["totals"]["known_minutes"], 60)

    def test_fetch_failure_retains_evidence_but_marks_result_incomplete(self):
        app = self.repo()
        self.commit(app, "VD-1 #time 1h #comment Work", "2026-09-25T12:00:00")
        with patch.object(scrum, "fetch", side_effect=GitCommandError(str(app), "fetch", "offline")):
            result = self.collect()
        self.assertFalse(result["complete"])
        self.assertEqual(result["totals"]["commit_count"], 1)
        self.assertIn("offline", result["warnings"][0]["message"])

    def test_broken_repository_reports_failure_and_keeps_successful_repository(self):
        app = self.repo()
        self.commit(app, "VD-1 #time 1h #comment Work", "2026-09-25T12:00:00")
        broken = self.root / "broken"
        broken.mkdir()
        (broken / ".git").write_text("not a Git file\n")
        result = self.collect()
        self.assertFalse(result["complete"])
        self.assertTrue(result["errors"])
        self.assertEqual(result["totals"]["commit_count"], 1)

    def test_empty_root_is_distinct_from_repository_with_no_recent_activity(self):
        result = self.collect()
        self.assertFalse(result["complete"])
        self.assertTrue(result["errors"])
        self.repo()
        result = self.collect()
        self.assertTrue(result["complete"])
        self.assertEqual(result["projects"], [])

    def test_stash_snapshots_do_not_create_a_workday(self):
        app = self.repo()
        source = app / "app.py"
        source.write_text("original\n")
        self.git(app, "add", "app.py")
        self.commit(app, "VD-1 #time 1h #comment Friday work", "2026-09-25T12:00:00")
        source.write_text("unfinished\n")
        (app / "draft.py").write_text("untracked\n")
        env = os.environ.copy()
        stamp = datetime(2026, 9, 27, 18).astimezone().isoformat()
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp,
                   GIT_AUTHOR_NAME="Tester", GIT_COMMITTER_NAME="Tester",
                   GIT_AUTHOR_EMAIL="tester@example.com", GIT_COMMITTER_EMAIL="tester@example.com")
        self.git(app, "stash", "push", "-u", env=env)
        result = self.collect()
        self.assertEqual(result["previous_work_date"], "2026-09-25")
        self.assertEqual(result["totals"]["commit_count"], 1)
        self.assertEqual(result["totals"]["wip_file_count"], 0)

    def test_custom_merge_subject_does_not_create_a_workday(self):
        app = self.repo()
        self.commit(app, "VD-1 #time 1h #comment Base work", "2026-09-25T12:00:00")
        base_branch = self.git(app, "branch", "--show-current")
        self.git(app, "checkout", "-b", "feature")
        self.commit(app, "VD-2 #time 1h #comment Feature work", "2026-09-25T13:00:00")
        self.git(app, "checkout", base_branch)
        self.commit(app, "VD-3 #time 1h #comment Main work", "2026-09-25T14:00:00")
        env = os.environ.copy()
        stamp = datetime(2026, 9, 27, 18).astimezone().isoformat()
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp,
                   GIT_AUTHOR_NAME="Tester", GIT_COMMITTER_NAME="Tester",
                   GIT_AUTHOR_EMAIL="tester@example.com", GIT_COMMITTER_EMAIL="tester@example.com")
        self.git(app, "merge", "feature", "--no-ff", "-m", "VD-9 #time 3h #comment Combine", env=env)
        result = self.collect()
        self.assertEqual(result["previous_work_date"], "2026-09-25")
        self.assertEqual(result["totals"]["commit_count"], 3)
        self.assertEqual(result["totals"]["known_minutes"], 180)

    def test_cli_stdout_is_json_and_does_not_load_environment_or_write_reports(self):
        app = self.repo()
        self.commit(app, "VD-1 #time 1h #comment Work", "2026-09-25T12:00:00")
        output = io.StringIO()
        collect = scrum.collect_scrum
        with patch.object(scrum, "_read_config_file", return_value=self.config), \
                patch.object(scrum, "collect_scrum", side_effect=lambda config, target, days:
                             collect(config, target, days, now=self.now)), \
                patch("lib.config._load_env", side_effect=AssertionError("must not load .env")), \
                redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = scrum.main(["--date", "2026-09-28"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["complete"])
        self.assertFalse((self.base / "notes").exists())
        self.assertFalse((self.base / "custom-reports").exists())

    def test_invalid_cli_configuration_returns_json_and_nonzero(self):
        output = io.StringIO()
        with patch.object(scrum, "_read_config_file", side_effect=ConfigError("missing config")), \
                redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = scrum.main([])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output.getvalue())["complete"])

    def test_invalid_dates_and_lookback_fail_before_collection(self):
        for kwargs in ({"target_date": "2026-09-29"}, {"target_date": "20260928"},
                       {"target_date": ""},
                       {"days": 0}, {"days": 3651}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.collect(**kwargs)


if __name__ == "__main__":
    unittest.main()
