import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import lib.config as config


class ConfigCliTests(unittest.TestCase):
    def test_parse_args_prints_version_without_requiring_config(self):
        stdout = io.StringIO()

        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(stdout):
                config.parse_args(["--version"])

        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("Daily Code Learn 0.1.0", stdout.getvalue())

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

    def test_doctor_reports_missing_config_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, "config", "profiles.json")

            stdout = io.StringIO()
            with patch.object(config, "CONFIG_PATH", config_path):
                with redirect_stdout(stdout):
                    self.assertEqual(config.run_doctor(), 1)

            self.assertIn("설정 파일 없음", stdout.getvalue())

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


if __name__ == "__main__":
    unittest.main()
