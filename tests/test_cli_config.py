import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import lib.config as config


class ConfigCliTests(unittest.TestCase):
    def _valid_config(self, root_path, output_dir):
        return {
            "roots": [{
                "name": "work",
                "path": root_path,
                "maxDepth": 1,
                "authorNames": ["Test User"],
                "authorEmails": ["test@example.com"],
            }],
            "outputDir": output_dir,
            "report": {
                "includeUncommittedDiff": True,
                "includeSensitiveFiles": False,
                "maxDiffLines": 0,
                "maxDiffBytes": 0,
            },
            "exclude": ["node_modules", "*.lock"],
            "telegram": {"enabled": False},
        }

    def test_load_env_accepts_an_owner_only_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = os.path.join(tmp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as file:
                file.write("TELEGRAM_BOT_TOKEN=private-token\n")
            os.chmod(env_path, 0o600)

            with patch.object(config, "PROJECT_ROOT", tmp_dir), \
                    patch.dict(os.environ, {}, clear=True):
                config._load_env()
                self.assertEqual(
                    os.environ["TELEGRAM_BOT_TOKEN"],
                    "private-token",
                )

    def test_load_env_refuses_group_or_other_permissions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = os.path.join(tmp_dir, ".env")
            with open(env_path, "w", encoding="utf-8") as file:
                file.write("TELEGRAM_BOT_TOKEN=exposed-token\n")
            os.chmod(env_path, 0o644)

            with patch.object(config, "PROJECT_ROOT", tmp_dir), \
                    patch.dict(os.environ, {}, clear=True), \
                    self.assertRaisesRegex(config.ConfigError, "chmod 600"):
                config._load_env()

            self.assertNotIn("TELEGRAM_BOT_TOKEN", os.environ)

    def test_load_env_refuses_a_symbolic_link(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_path = os.path.join(tmp_dir, "secrets")
            env_path = os.path.join(tmp_dir, ".env")
            with open(target_path, "w", encoding="utf-8") as file:
                file.write("TELEGRAM_BOT_TOKEN=linked-token\n")
            os.chmod(target_path, 0o600)
            try:
                os.symlink(target_path, env_path)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"symbolic links unavailable: {error}")

            with patch.object(config, "PROJECT_ROOT", tmp_dir), \
                    patch.dict(os.environ, {}, clear=True), \
                    self.assertRaises(config.ConfigError):
                config._load_env()

            self.assertNotIn("TELEGRAM_BOT_TOKEN", os.environ)

    def test_parse_args_prints_version_without_requiring_config(self):
        stdout = io.StringIO()

        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(stdout):
                config.parse_args(["--version"])

        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("Daily Code Learn 0.2.0", stdout.getvalue())

    def test_init_config_copies_example_without_overwriting_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_dir = os.path.join(tmp_dir, "config")
            os.makedirs(config_dir)
            example_path = os.path.join(config_dir, "profiles.example.json")
            target_path = os.path.join(config_dir, "profiles.json")
            with open(example_path, "w", encoding="utf-8") as f:
                json.dump({"roots": []}, f)

            stdout = io.StringIO()
            with patch.object(config, "EXAMPLE_PATH", example_path), patch.object(config, "CONFIG_PATH", target_path):
                with redirect_stdout(stdout):
                    self.assertEqual(config.init_config(), 0)

                with open(target_path, "r", encoding="utf-8") as f:
                    self.assertEqual(json.load(f), {"roots": []})

                with open(target_path, "w", encoding="utf-8") as f:
                    json.dump({"custom": True}, f)

                with redirect_stdout(stdout):
                    self.assertEqual(config.init_config(), 0)

                with open(target_path, "r", encoding="utf-8") as f:
                    self.assertEqual(json.load(f), {"custom": True})

            output = stdout.getvalue()
            self.assertIn("설정 파일을 생성했습니다", output)
            self.assertIn("이미 설정 파일이 있습니다", output)

    def test_init_config_reports_copy_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            example_path = os.path.join(tmp_dir, "profiles.example.json")
            target_path = os.path.join(tmp_dir, "config", "profiles.json")
            with open(example_path, "w", encoding="utf-8") as file:
                file.write("{}")

            stdout = io.StringIO()
            with patch.object(config, "EXAMPLE_PATH", example_path), \
                    patch.object(config, "CONFIG_PATH", target_path), \
                    patch.object(config.shutil, "copyfile", side_effect=PermissionError("denied")), \
                    redirect_stdout(stdout):
                exit_code = config.init_config()

            self.assertEqual(exit_code, 1)
            self.assertIn("설정 파일 생성 실패", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())

    def test_doctor_reports_missing_config_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "config", "profiles.json")

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path):
                with redirect_stdout(stdout):
                    self.assertEqual(config.run_doctor(), 1)

            self.assertIn("설정 파일 없음", stdout.getvalue())

    def test_doctor_reports_missing_git_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    patch.object(config.shutil, "which", return_value=None), \
                    redirect_stdout(stdout):
                exit_code = config.run_doctor()

            self.assertEqual(exit_code, 1)
            self.assertIn("Git 실행 파일을 찾을 수 없습니다", stdout.getvalue())

    def test_check_git_accepts_supported_version_and_rejects_old_version(self):
        with patch.object(config.shutil, "which", return_value="/usr/bin/git"), \
                patch.object(config.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "git version 2.37.0\n"
            run.return_value.stderr = ""

            version, error = config._check_git()

            self.assertEqual(version, "git version 2.37.0")
            self.assertIsNone(error)

            run.return_value.stdout = "git version 2.36.6 (Apple Git-122)\n"
            version, error = config._check_git()

            self.assertIsNone(version)
            self.assertIn("Git 2.37.0 이상이 필요", error)
            self.assertIn("현재 버전: 2.36.6", error)

    def test_doctor_warns_about_placeholders_and_missing_roots(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_root = os.path.join(tmp_dir, "missing")
            config_path = os.path.join(tmp_dir, "config", "profiles.json")
            os.makedirs(os.path.dirname(config_path))
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "roots": [{
                        "name": "sample",
                        "path": missing_root,
                        "authorNames": ["Your Name"],
                        "authorEmails": ["me@example.com"],
                    }],
                    "outputDir": "./reports",
                    "telegram": {"enabled": True},
                }, f)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), patch.dict(os.environ, {}, clear=True):
                with redirect_stdout(stdout):
                    self.assertEqual(config.run_doctor(), 1)

            output = stdout.getvalue()
            self.assertIn("root 경로 없음", output)
            self.assertIn("authorEmails placeholder", output)
            self.assertIn("텔레그램 환경변수 없음", output)

    def test_validate_config_accepts_valid_values_and_creatable_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = os.path.join(tmp_dir, "new", "reports")
            value = self._valid_config(tmp_dir, output_dir)

            self.assertEqual(config.validate_config(value), [])

    def test_validate_config_reports_schema_and_value_errors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            invalid = {
                "roots": [
                    {
                        "name": "same",
                        "path": tmp_dir,
                        "authorNames": [""],
                        "authorEmails": [],
                    },
                    {
                        "name": "same",
                        "path": os.path.join(tmp_dir, "missing"),
                        "maxDepth": 0,
                        "authorNames": "Test User",
                        "authorEmails": ["test@example.com", 7],
                    },
                ],
                "outputDir": 123,
                "report": {
                    "includeUncommittedDiff": "false",
                    "includeSensitiveFiles": 1,
                    "maxDiffLines": -1,
                    "maxDiffBytes": -1,
                },
                "exclude": ["dist", 123],
                "telegram": {"enabled": "false"},
            }

            errors = "\n".join(config.validate_config(invalid))

            self.assertIn("root name은 중복", errors)
            self.assertIn("root 경로 없음", errors)
            self.assertIn("maxDepth는 1 이상의 정수", errors)
            self.assertIn("authorNames는 비어 있지 않은 문자열 목록", errors)
            self.assertIn("authorEmails는 비어 있지 않은 문자열 목록", errors)
            self.assertIn("outputDir은 비어 있지 않은 문자열", errors)
            self.assertIn("report.includeUncommittedDiff는 boolean", errors)
            self.assertIn("report.includeSensitiveFiles는 boolean", errors)
            self.assertIn("report.maxDiffLines는 0 이상의 정수", errors)
            self.assertIn("report.maxDiffBytes는 0 이상의 정수", errors)
            self.assertIn("exclude는 문자열 목록", errors)
            self.assertIn("telegram.enabled는 boolean", errors)

    def test_validate_config_rejects_non_object_sections_and_output_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_file = os.path.join(tmp_dir, "report.md")
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("existing file")

            value = self._valid_config(tmp_dir, output_file)
            value["roots"] = ["not-an-object"]
            value["report"] = []
            value["telegram"] = False

            errors = "\n".join(config.validate_config(value))

            self.assertIn("root는 JSON 객체", errors)
            self.assertIn("report는 JSON 객체", errors)
            self.assertIn("telegram은 JSON 객체", errors)
            self.assertIn("outputDir가 디렉터리가 아닙니다", errors)

    def test_validate_config_rejects_non_object_top_level_and_empty_roots(self):
        self.assertIn("최상위", config.validate_config([])[0])
        self.assertIn("roots 설정 없음", config.validate_config({"roots": []})[0])

    def test_validate_config_rejects_duplicate_or_overlapping_root_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            nested = os.path.join(tmp_dir, "nested")
            os.makedirs(nested)
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            second = dict(value["roots"][0])
            second.update({"name": "nested", "path": nested})
            value["roots"].append(second)

            errors = "\n".join(config.validate_config(value))

            self.assertIn("중복되거나 겹칩니다", errors)

    def test_validate_config_rejects_case_aliases_on_case_insensitive_filesystems(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_path = os.path.join(tmp_dir, "CaseRoot")
            alias_path = os.path.join(tmp_dir, "caseroot")
            os.makedirs(root_path)
            if not os.path.isdir(alias_path):
                self.skipTest("case-sensitive filesystem")
            if not os.path.samefile(root_path, alias_path):
                self.skipTest("paths are not filesystem aliases")
            value = self._valid_config(
                root_path,
                os.path.join(tmp_dir, "reports"),
            )
            second = dict(value["roots"][0])
            second.update({"name": "alias", "path": alias_path})
            value["roots"].append(second)

            errors = "\n".join(config.validate_config(value))

            self.assertIn("중복되거나 겹칩니다", errors)

    def test_validate_config_rejects_blank_root_name_and_boolean_integers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            value["roots"][0]["name"] = "  "
            value["roots"][0]["maxDepth"] = True
            value["report"]["maxDiffLines"] = True
            value["report"]["maxDiffBytes"] = True

            errors = "\n".join(config.validate_config(value))

            self.assertIn("name은 비어 있지 않은 문자열", errors)
            self.assertIn("maxDepth는 1 이상의 정수", errors)
            self.assertIn("maxDiffLines는 0 이상의 정수", errors)
            self.assertIn("maxDiffBytes는 0 이상의 정수", errors)

    def test_load_config_reports_malformed_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write('{"roots": [}')

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"):
                with self.assertRaises(SystemExit) as ctx, redirect_stdout(stdout):
                    config.load_config()

            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("설정 JSON 파싱 실패", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())

    def test_load_config_reports_read_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("{}")

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    patch.object(
                        config,
                        "_read_config_file",
                        side_effect=config.ConfigError("설정 파일 읽기 실패: denied"),
                    ):
                with self.assertRaises(SystemExit) as ctx, redirect_stdout(stdout):
                    config.load_config()

            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("설정 파일 읽기 실패: denied", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())

    def test_load_config_uses_shared_validation_before_returning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"roots": []}, f)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"):
                with self.assertRaises(SystemExit) as ctx, redirect_stdout(stdout):
                    config.load_config()

            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("roots 설정 없음", stdout.getvalue())
            self.assertIn("--doctor", stdout.getvalue())

    def test_load_config_escapes_controls_in_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            malicious_name = "work\x1b[2J\nforged"
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump({
                    "roots": [{
                        "name": malicious_name,
                        "path": os.path.join(tmp_dir, "missing"),
                        "authorNames": ["Test User"],
                        "authorEmails": ["test@example.com"],
                    }],
                    "outputDir": os.path.join(tmp_dir, "reports"),
                }, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    redirect_stdout(stdout), \
                    self.assertRaises(SystemExit):
                config.load_config()

            output = stdout.getvalue()
            self.assertNotIn("\x1b", output)
            self.assertIn(r"work\x1b[2J\nforged", output)

    def test_load_config_keeps_telegram_enabled_when_credentials_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            value["telegram"]["enabled"] = True
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    patch.dict(os.environ, {}, clear=True), \
                    redirect_stdout(stdout):
                loaded = config.load_config()

            self.assertTrue(loaded["telegram"]["enabled"])
            self.assertNotIn("bot_token", loaded["telegram"])
            self.assertIn("전송을 요청하면 실패", stdout.getvalue())

    def test_load_config_discards_persisted_telegram_credentials(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            value["telegram"].update({
                "enabled": True,
                "bot_token": "persisted-token",
                "chat_id": "persisted-chat",
            })
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    patch.dict(os.environ, {}, clear=True), \
                    redirect_stdout(stdout):
                loaded = config.load_config()

            self.assertTrue(loaded["telegram"]["enabled"])
            self.assertNotIn("bot_token", loaded["telegram"])
            self.assertNotIn("chat_id", loaded["telegram"])
            self.assertNotIn("persisted-token", stdout.getvalue())
            self.assertIn("전송을 요청하면 실패", stdout.getvalue())

    def test_doctor_handles_non_object_config_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump([], f)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), redirect_stdout(stdout):
                self.assertEqual(config.run_doctor(), 1)

            self.assertIn("최상위 값은 JSON 객체", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())

    def test_doctor_handles_invalid_scan_depth_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            value["roots"][0]["maxDepth"] = "2"
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), redirect_stdout(stdout):
                exit_code = config.run_doctor()

            self.assertEqual(exit_code, 1)
            self.assertIn("maxDepth는 1 이상의 정수", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())

    def test_doctor_handles_repository_scan_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    patch.object(config, "scan_repos", side_effect=PermissionError("denied")), \
                    redirect_stdout(stdout):
                exit_code = config.run_doctor()

            self.assertEqual(exit_code, 1)
            self.assertIn("저장소 탐색 실패", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())

    def test_doctor_treats_an_empty_scan_range_as_setup_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    redirect_stdout(stdout):
                exit_code = config.run_doctor()

            self.assertEqual(exit_code, 1)
            self.assertIn("0개 git 저장소", stdout.getvalue())
            self.assertIn("저장소를 찾지 못했습니다", stdout.getvalue())

    def test_doctor_escapes_controls_in_root_labels_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_path = os.path.join(tmp_dir, "root\x1b[2J\nforged")
            os.makedirs(root_path)
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(
                root_path,
                os.path.join(tmp_dir, "reports"),
            )
            value["roots"][0]["name"] = "work\x1b[31m\nforged"
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    patch.object(
                        config,
                        "_check_git",
                        return_value=("git version 2.37.0", None),
                    ), \
                    redirect_stdout(stdout):
                exit_code = config.run_doctor()

            output = stdout.getvalue()
            self.assertEqual(exit_code, 1)
            self.assertNotIn("\x1b", output)
            self.assertIn(r"work\x1b[31m\nforged", output)
            self.assertIn(r"root\x1b[2J\nforged", output)

    def test_doctor_succeeds_for_supported_git_and_discovered_repository(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repository = os.path.join(tmp_dir, "sample-app")
            os.makedirs(repository)
            subprocess.run(
                ["git", "init"],
                cwd=repository,
                check=True,
                capture_output=True,
            )
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    patch.object(
                        config,
                        "_check_git",
                        return_value=("git version 2.37.0", None),
                    ), \
                    redirect_stdout(stdout):
                exit_code = config.run_doctor()

            self.assertEqual(exit_code, 0)
            self.assertIn("1개 git 저장소", stdout.getvalue())
            self.assertIn("기본 설정이 정상", stdout.getvalue())

    def test_doctor_rejects_a_stale_git_marker(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repository = os.path.join(tmp_dir, "broken")
            os.makedirs(os.path.join(repository, ".git"))
            config_path = os.path.join(tmp_dir, "profiles.json")
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            with open(config_path, "w", encoding="utf-8") as file:
                json.dump(value, file)

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), \
                    patch.object(
                        config,
                        "_check_git",
                        return_value=("git version 2.37.0", None),
                    ), \
                    redirect_stdout(stdout):
                exit_code = config.run_doctor()

            self.assertEqual(exit_code, 1)
            self.assertIn("유효하지 않은 저장소", stdout.getvalue())

    def test_doctor_reports_malformed_json_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "profiles.json")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("not json")

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path), \
                    patch.object(config, "_load_env"), redirect_stdout(stdout):
                self.assertEqual(config.run_doctor(), 1)

            self.assertIn("설정 JSON 파싱 실패", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())

    def test_validate_config_rejects_unwritable_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            value = self._valid_config(tmp_dir, os.path.join(tmp_dir, "reports"))
            os.mkdir(value["outputDir"])

            with patch.object(config.os, "access", return_value=False):
                errors = "\n".join(config.validate_config(value))

            self.assertIn("outputDir에 읽기·쓰기·탐색 권한이 없습니다", errors)

    def test_validate_config_checks_read_write_and_search_output_permissions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = os.path.join(tmp_dir, "reports")
            os.mkdir(output_dir)
            value = self._valid_config(tmp_dir, output_dir)
            checked_modes = []

            def deny_access(_path, mode):
                checked_modes.append(mode)
                return False

            with patch.object(config.os, "access", side_effect=deny_access):
                config.validate_config(value)

            self.assertEqual(
                checked_modes,
                [os.R_OK | os.W_OK | os.X_OK],
            )

    def test_days_requires_check_missed(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stderr(stderr):
            config.parse_args(["--days", "7"])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--days 는 --check-missed", stderr.getvalue())

        args = config.parse_args(["--check-missed", "--days=7"])
        self.assertTrue(args.check_missed)
        self.assertEqual(args.days, 7)

        args = config.parse_args([])
        self.assertEqual(args.days, 30)

        for invalid_days in ("0", "3651", "1000000"):
            with self.subTest(invalid_days=invalid_days):
                stderr = io.StringIO()
                with self.assertRaises(SystemExit) as context, redirect_stderr(
                    stderr
                ):
                    config.parse_args(["--check-missed", "--days", invalid_days])
                self.assertEqual(context.exception.code, 2)

    def test_abbreviated_days_still_requires_check_missed(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stderr(stderr):
            config.parse_args(["--day", "7"])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--days 는 --check-missed", stderr.getvalue())

    def test_utility_modes_reject_incompatible_options(self):
        for argv in (
            ["--init", "--no-notify"],
            ["--doctor", "--notify"],
            ["--doctor", "--include-current-changes"],
        ):
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                with self.assertRaises(SystemExit) as ctx, redirect_stderr(stderr):
                    config.parse_args(argv)
                self.assertEqual(ctx.exception.code, 2)
                self.assertIn("리포트 생성 옵션", stderr.getvalue())

    def test_init_and_doctor_are_mutually_exclusive(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as ctx, redirect_stderr(stderr):
            config.parse_args(["--init", "--doctor"])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_include_current_changes_resolves_once_for_target_date(self):
        self.assertTrue(config.parse_args([]).include_current_changes)
        self.assertFalse(
            config.parse_args(["--date", "2020-01-01"]).include_current_changes
        )
        self.assertTrue(
            config.parse_args([
                "--date",
                "2020-01-01",
                "--include-current-changes",
            ]).include_current_changes
        )
        self.assertFalse(
            config.parse_args(["--check-missed"]).include_current_changes
        )

    def test_invalid_date_uses_argparse_exit_code(self):
        for invalid_date in ("2026-02-30", "2026-2-03"):
            with self.subTest(invalid_date=invalid_date):
                stderr = io.StringIO()
                with self.assertRaises(SystemExit) as context, redirect_stderr(stderr):
                    config.parse_args(["--date", invalid_date])

                self.assertEqual(context.exception.code, 2)
                self.assertIn("잘못된 날짜 형식", stderr.getvalue())

    def test_explicit_empty_date_is_not_treated_as_omitted(self):
        cases = [
            (["--date", ""], "잘못된 날짜 형식"),
            (
                ["--check-missed", "--date", ""],
                "--date 와 --check-missed",
            ),
            (["--init", "--date", ""], "--init/--doctor"),
        ]
        for argv, expected_message in cases:
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                with self.assertRaises(SystemExit) as context, redirect_stderr(
                    stderr
                ):
                    config.parse_args(argv)

                self.assertEqual(context.exception.code, 2)
                self.assertIn(expected_message, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
