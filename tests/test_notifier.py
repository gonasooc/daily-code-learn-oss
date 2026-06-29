import os
import tempfile
import unittest

import lib.notifier as notifier


class NotifierFailureTests(unittest.TestCase):
    def test_send_file_as_messages_returns_false_when_a_part_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "codex-analysis.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("# Analysis\n\nhello\n")

            original = notifier.send_telegram_message
            try:
                def fail_send(_bot_token, _chat_id, _text):
                    raise RuntimeError("network down")

                notifier.send_telegram_message = fail_send

                self.assertIs(
                    notifier.send_file_as_messages("token", "chat", file_path, "2026-06-28"),
                    False,
                )
            finally:
                notifier.send_telegram_message = original

    def test_notify_returns_false_when_any_file_fails(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            with open(os.path.join(report_dir, "codex-analysis.md"), "w", encoding="utf-8") as f:
                f.write("# Analysis\n")

            original = notifier.send_file_as_messages
            try:
                notifier.send_file_as_messages = lambda *_args: False

                config = {
                    "telegram": {
                        "enabled": True,
                        "bot_token": "token",
                        "chat_id": "chat",
                    }
                }

                self.assertIs(notifier.notify(config, "2026-06-28", output_dir), False)
            finally:
                notifier.send_file_as_messages = original

    def test_send_file_as_messages_returns_true_when_all_parts_send(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "codex-analysis.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("# Analysis\n\nhello\n")

            original = notifier.send_telegram_message
            try:
                notifier.send_telegram_message = lambda *_args: True

                self.assertIs(
                    notifier.send_file_as_messages("token", "chat", file_path, "2026-06-28"),
                    True,
                )
            finally:
                notifier.send_telegram_message = original


if __name__ == "__main__":
    unittest.main()
