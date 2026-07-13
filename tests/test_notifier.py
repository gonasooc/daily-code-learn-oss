import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import lib.notifier as notifier
from lib.renderer import write_report


def _report():
    return {
        "project_name": "sample-app",
        "root_name": "work",
        "repo_relative_path": "sample-app",
        "repo_path": "/workspace/sample-app",
        "branch": "main",
        "author_names": ["Tester"],
        "commits": [],
        "staged_files": [],
        "unstaged_files": [],
        "untracked_files": [],
    }


class NotifierFailureTests(unittest.TestCase):
    def test_send_message_requires_telegram_ok_response(self):
        class FakeResponse(io.BytesIO):
            def __init__(self, payload, status=200):
                super().__init__(json.dumps(payload).encode("utf-8"))
                self.status = status

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        original = notifier.urllib.request.urlopen
        try:
            notifier.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(
                {"ok": False}
            )
            self.assertFalse(notifier.send_telegram_message("token", "chat", "text"))

            notifier.urllib.request.urlopen = lambda *_args, **_kwargs: FakeResponse(
                {"ok": True, "result": {}}
            )
            self.assertTrue(notifier.send_telegram_message("token", "chat", "text"))
        finally:
            notifier.urllib.request.urlopen = original

    def assert_valid_chunks(self, chunks, max_length=notifier.MAX_MESSAGE_LENGTH):
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertLessEqual(notifier._message_units(chunk), max_length)
            stack = []
            for match in re.finditer(r"</?(b|code|pre)>", chunk):
                tag_name = match.group(1)
                if match.group(0).startswith("</"):
                    self.assertTrue(stack, f"여는 태그 없이 닫힘: {chunk!r}")
                    self.assertEqual(stack.pop(), tag_name)
                else:
                    stack.append(tag_name)
            self.assertEqual(stack, [], f"닫히지 않은 태그: {chunk!r}")

    def test_split_message_balances_pre_tags_for_a_long_code_line(self):
        code = "x" * (notifier.MAX_MESSAGE_LENGTH * 3)
        html = f"<pre>\n{code}\n</pre>"

        chunks = notifier.split_message(html)

        self.assertGreater(len(chunks), 1)
        self.assert_valid_chunks(chunks)
        self.assertTrue(all(chunk.startswith("<pre>") for chunk in chunks))
        self.assertTrue(all(chunk.endswith("</pre>") for chunk in chunks))
        reconstructed = "".join(
            chunk.replace("<pre>", "").replace("</pre>", "") for chunk in chunks
        )
        self.assertEqual(reconstructed, f"\n{code}\n")

    def test_split_message_keeps_nested_html_balanced_within_limit(self):
        html = f"<b>heading <code>{'&amp;' * 100}</code></b>"

        chunks = notifier.split_message(html, max_length=64)

        self.assertGreater(len(chunks), 1)
        self.assert_valid_chunks(chunks, max_length=64)
        reconstructed = "".join(
            re.sub(r"</?(?:b|code|pre)>", "", chunk) for chunk in chunks
        )
        self.assertEqual(reconstructed, f"heading {'&amp;' * 100}")

    def test_split_message_counts_non_bmp_characters_conservatively(self):
        text = "😀" * 3000

        chunks = notifier.split_message(text)

        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text)
        self.assert_valid_chunks(chunks)

    def test_crossing_inline_markdown_never_creates_crossing_html(self):
        html = notifier._md_to_telegram_html("# **foo `bar** baz`")

        chunks = notifier.split_message(html, max_length=64)

        self.assert_valid_chunks(chunks, max_length=64)
        self.assertIn("<code>bar** baz</code>", html)

    def test_variable_length_inline_code_preserves_inner_backticks(self):
        html = notifier._md_to_telegram_html("- `` path`with`ticks ``")

        self.assertIn("<code> path`with`ticks </code>", html)
        self.assertEqual(html.count("<code>"), 1)
        self.assertEqual(html.count("</code>"), 1)

    def test_variable_length_fence_closes_only_on_matching_delimiter(self):
        markdown = "````diff\n```\nvalue\n````"

        html = notifier._md_to_telegram_html(markdown)

        self.assertEqual(html, "<pre>\n```\nvalue\n</pre>")

    def test_internal_report_identity_marker_is_not_sent(self):
        marker = "<!-- daily-code-learn-report:v1:" + ("a" * 64) + " -->"

        html = notifier._md_to_telegram_html(f"# Report\n{marker}\nbody")

        self.assertNotIn("daily-code-learn-report", html)
        self.assertIn("body", html)

    def test_special_markdown_path_fails_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            special_path = os.path.join(tmp_dir, "special.md")
            os.mkdir(special_path)

            self.assertFalse(notifier.send_file_as_messages(
                "token",
                "chat",
                special_path,
                "2026-06-28",
            ))

    def test_oversized_markdown_is_rejected_before_conversion(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "large.md")
            with open(file_path, "wb") as file:
                file.truncate(notifier.MAX_FILE_SIZE_BYTES + 1)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = notifier.send_file_as_messages(
                    "token",
                    "chat",
                    file_path,
                    "2026-06-28",
                )

            self.assertFalse(result)
            self.assertIn("byte 제한", stdout.getvalue())

    def test_message_count_limit_rejects_before_any_partial_delivery(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "many-messages.md")
            with open(file_path, "w", encoding="utf-8") as file:
                file.write(
                    "x" * (
                        notifier.MAX_MESSAGE_LENGTH
                        * notifier.MAX_MESSAGES_PER_FILE
                    )
                )
            sent = []
            stdout = io.StringIO()

            with patch.object(
                notifier,
                "send_telegram_message",
                side_effect=lambda *_args: sent.append(True) or True,
            ), redirect_stdout(stdout):
                result = notifier.send_file_as_messages(
                    "token",
                    "chat",
                    file_path,
                    "2026-06-28",
                )

            self.assertFalse(result)
            self.assertEqual(sent, [])
            self.assertIn("100개 제한", stdout.getvalue())

    def test_telegram_payload_escapes_content_and_header_controls(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "report.md")
            with open(file_path, "w", encoding="utf-8") as file:
                file.write("body\x1b[2J\u202enext")
            sent = []

            with patch.object(
                notifier,
                "send_telegram_message",
                side_effect=lambda _token, _chat, text: sent.append(text) or True,
            ):
                result = notifier.send_file_as_messages(
                    "token",
                    "chat",
                    file_path,
                    "2026-06-28\nforged\u2066",
                )

            payload = "".join(sent)
            self.assertTrue(result)
            self.assertNotIn("\x1b", payload)
            self.assertNotIn("\u202e", payload)
            self.assertNotIn("\u2066", payload)
            self.assertIn(r"body\x1b[2J\u202enext", payload)
            self.assertIn(r"2026-06-28\nforged\u2066", payload)

    def test_explicit_notify_fails_loudly_when_telegram_is_disabled(self):
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            result = notifier.notify(
                {"telegram": {"enabled": False}},
                "2026-06-28",
                "/reports",
            )

        self.assertFalse(result)
        self.assertIn("비활성화", stdout.getvalue())

    def test_standalone_notify_file_fails_when_telegram_is_disabled(self):
        stdout = io.StringIO()

        with patch(
            "lib.config.load_config",
            return_value={"telegram": {"enabled": False}},
        ), redirect_stdout(stdout):
            result = notifier.notify_file("report.md", "2026-06-28")

        self.assertFalse(result)
        self.assertIn("비활성화", stdout.getvalue())

    def test_symlink_markdown_path_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_path = os.path.join(tmp_dir, "outside.txt")
            link_path = os.path.join(tmp_dir, "report.md")
            with open(target_path, "w", encoding="utf-8") as file:
                file.write("secret")
            os.symlink(target_path, link_path)

            self.assertFalse(notifier.send_file_as_messages(
                "token",
                "chat",
                link_path,
                "2026-06-28",
            ))

    def test_file_conversion_error_escapes_terminal_controls(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "report\x1b[2J\nforged.md")
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = notifier.send_file_as_messages(
                    "token",
                    "chat",
                    file_path,
                    "2026-06-28",
                )

            output = stdout.getvalue()
            self.assertFalse(result)
            self.assertNotIn("\x1b", output)
            self.assertIn(r"report\x1b[2J\nforged.md", output)

    def test_invalid_requested_path_escapes_terminal_controls(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            invalid_path = os.path.join(
                report_dir,
                "missing\x1b[31m\rforged.md",
            )
            stdout = io.StringIO()
            config = {
                "telegram": {
                    "enabled": True,
                    "bot_token": "token",
                    "chat_id": "chat",
                }
            }

            with redirect_stdout(stdout):
                result = notifier.notify(
                    config,
                    "2026-06-28",
                    output_dir,
                    file_paths=[invalid_path],
                )

            output = stdout.getvalue()
            self.assertFalse(result)
            self.assertNotIn("\x1b", output)
            self.assertNotIn("\r", output)
            self.assertIn(r"missing\x1b[31m\rforged.md", output)

    def test_send_file_as_messages_splits_a_long_header_within_limit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "report.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("body")

            sent_chunks = []
            original = notifier.send_telegram_message
            try:
                def capture_send(_bot_token, _chat_id, text):
                    sent_chunks.append(text)
                    return True

                notifier.send_telegram_message = capture_send
                result = notifier.send_file_as_messages(
                    "token",
                    "chat",
                    file_path,
                    "2" * (notifier.MAX_MESSAGE_LENGTH * 2),
                )
            finally:
                notifier.send_telegram_message = original

        self.assertIs(result, True)
        self.assertGreater(len(sent_chunks), 1)
        self.assert_valid_chunks(sent_chunks)
        self.assertTrue(sent_chunks[0].startswith("<b>📋 "))

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

    def test_transport_failure_does_not_print_the_bot_token(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "report.md")
            with open(file_path, "w", encoding="utf-8") as file:
                file.write("# Report\n")
            token = "secret token"
            stdout = io.StringIO()
            original = notifier.send_telegram_message
            try:
                notifier.send_telegram_message = lambda *_args: (_ for _ in ()).throw(
                    RuntimeError(f"/bot{token}/sendMessage")
                )
                with redirect_stdout(stdout):
                    result = notifier.send_file_as_messages(
                        token,
                        "chat",
                        file_path,
                        "2026-06-28",
                    )
            finally:
                notifier.send_telegram_message = original

            self.assertFalse(result)
            self.assertNotIn(token, stdout.getvalue())
            self.assertIn("RuntimeError", stdout.getvalue())

    def test_notify_returns_false_when_any_file_fails(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            with open(os.path.join(report_dir, "codex-analysis.md"), "w", encoding="utf-8") as f:
                f.write("# Analysis\n")

            original = notifier.send_file_as_messages
            try:
                notifier.send_file_as_messages = lambda *_args, **_kwargs: False

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

    def test_notify_does_not_follow_a_symlink_date_directory(self):
        with tempfile.TemporaryDirectory() as output_dir, \
                tempfile.TemporaryDirectory() as outside_dir:
            with open(
                os.path.join(outside_dir, "secret.md"),
                "w",
                encoding="utf-8",
            ) as file:
                file.write("secret")
            try:
                os.symlink(
                    outside_dir,
                    os.path.join(output_dir, "2026-06-28"),
                    target_is_directory=True,
                )
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks unavailable: {error}")
            config = {
                "telegram": {
                    "enabled": True,
                    "bot_token": "token",
                    "chat_id": "chat",
                }
            }

            with patch.object(notifier, "send_file_as_messages") as send_mock:
                result = notifier.notify(
                    config,
                    "2026-06-28",
                    output_dir,
                )

            self.assertFalse(result)
            send_mock.assert_not_called()

    def test_notify_stays_on_open_directory_if_date_path_is_swapped(self):
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
                file.write("safe report")
            with open(
                os.path.join(outside_dir, "report.md"),
                "w",
                encoding="utf-8",
            ) as file:
                file.write("external secret")
            config = {
                "telegram": {
                    "enabled": True,
                    "bot_token": "token",
                    "chat_id": "chat",
                }
            }
            real_listdir = os.listdir

            def swap_then_list(directory_fd):
                os.rename(report_dir, moved_dir)
                os.symlink(outside_dir, report_dir, target_is_directory=True)
                return real_listdir(directory_fd)

            sent = []
            try:
                with patch.object(
                    notifier.os,
                    "listdir",
                    side_effect=swap_then_list,
                ), patch.object(
                    notifier,
                    "send_telegram_message",
                    side_effect=lambda _token, _chat, text: sent.append(text) or True,
                ):
                    result = notifier.notify(
                        config,
                        "2026-06-28",
                        output_dir,
                    )
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory swap unavailable: {error}")

            self.assertTrue(result)
            self.assertIn("safe report", "".join(sent))
            self.assertNotIn("external secret", "".join(sent))

    def test_current_run_artifact_rejects_directory_replaced_between_calls(self):
        with tempfile.TemporaryDirectory() as output_dir:
            artifact = write_report(_report(), "2026-06-28", output_dir)
            report_dir = os.path.dirname(artifact)
            moved_dir = os.path.join(output_dir, "moved-date")
            file_name = os.path.basename(artifact)
            os.rename(report_dir, moved_dir)
            os.makedirs(report_dir)
            with open(
                os.path.join(report_dir, file_name),
                "w",
                encoding="utf-8",
            ) as file:
                file.write("external secret")
            config = {
                "telegram": {
                    "enabled": True,
                    "bot_token": "token",
                    "chat_id": "chat",
                }
            }

            with patch.object(notifier, "send_telegram_message") as send_mock:
                result = notifier.notify(
                    config,
                    "2026-06-28",
                    output_dir,
                    file_paths=[artifact],
                )

            self.assertFalse(result)
            send_mock.assert_not_called()

    def test_current_run_artifact_rejects_in_place_content_change(self):
        with tempfile.TemporaryDirectory() as output_dir:
            artifact = write_report(_report(), "2026-06-28", output_dir)
            with open(artifact, "w", encoding="utf-8") as file:
                file.write("changed in place")
            config = {
                "telegram": {
                    "enabled": True,
                    "bot_token": "token",
                    "chat_id": "chat",
                }
            }

            with patch.object(notifier, "send_telegram_message") as send_mock:
                result = notifier.notify(
                    config,
                    "2026-06-28",
                    output_dir,
                    file_paths=[artifact],
                )

            self.assertFalse(result)
            send_mock.assert_not_called()

    def test_notify_can_limit_delivery_to_files_from_current_run(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            current = os.path.join(report_dir, "current.md")
            stale = os.path.join(report_dir, "stale.md")
            for path in (current, stale):
                with open(path, "w", encoding="utf-8") as file:
                    file.write("# Report\n")

            delivered = []
            original = notifier.send_file_as_messages
            try:
                def capture(_token, _chat, file_path, _date, **_kwargs):
                    delivered.append(file_path)
                    return True

                notifier.send_file_as_messages = capture
                config = {
                    "telegram": {
                        "enabled": True,
                        "bot_token": "token",
                        "chat_id": "chat",
                    }
                }

                result = notifier.notify(
                    config,
                    "2026-06-28",
                    output_dir,
                    file_paths=[current],
                )
            finally:
                notifier.send_file_as_messages = original

            self.assertTrue(result)
            self.assertEqual(delivered, [current])

    def test_notify_reports_missing_requested_file_after_sending_existing(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            current = os.path.join(report_dir, "current.md")
            missing = os.path.join(report_dir, "missing.md")
            with open(current, "w", encoding="utf-8") as file:
                file.write("# Report\n")
            delivered = []
            original = notifier.send_file_as_messages
            try:
                notifier.send_file_as_messages = lambda _token, _chat, path, _date, **_kwargs: (
                    delivered.append(path) or True
                )
                config = {
                    "telegram": {
                        "enabled": True,
                        "bot_token": "token",
                        "chat_id": "chat",
                    }
                }

                result = notifier.notify(
                    config,
                    "2026-06-28",
                    output_dir,
                    file_paths=[current, missing],
                )
            finally:
                notifier.send_file_as_messages = original

            self.assertFalse(result)
            self.assertEqual(delivered, [current])

    def test_notify_fails_when_enabled_credentials_are_missing(self):
        with tempfile.TemporaryDirectory() as output_dir:
            os.makedirs(os.path.join(output_dir, "2026-06-28"))

            self.assertFalse(notifier.notify(
                {"telegram": {"enabled": True}},
                "2026-06-28",
                output_dir,
            ))

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

    def test_send_file_as_messages_returns_false_when_api_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, "codex-analysis.md")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("# Analysis\n\nhello\n")

            calls = []
            original = notifier.send_telegram_message
            try:
                def reject_send(_bot_token, _chat_id, text):
                    calls.append(text)
                    return False

                notifier.send_telegram_message = reject_send

                self.assertIs(
                    notifier.send_file_as_messages("token", "chat", file_path, "2026-06-28"),
                    False,
                )
                self.assertEqual(len(calls), 1)
            finally:
                notifier.send_telegram_message = original


if __name__ == "__main__":
    unittest.main()
