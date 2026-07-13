import io
import unittest

from lib import colors


class FakeTty(io.StringIO):
    def isatty(self):
        return True


class ColorTests(unittest.TestCase):
    def test_non_tty_output_is_plain_by_default(self):
        stream = io.StringIO()

        self.assertFalse(colors.supports_color(stream=stream, environ={}))
        self.assertEqual(colors.green("done", stream=stream, environ={}), "done")

    def test_tty_output_uses_ansi_by_default(self):
        stream = FakeTty()

        self.assertTrue(colors.supports_color(stream=stream, environ={}))
        self.assertEqual(
            colors.green("done", stream=stream, environ={}),
            f"{colors.GREEN}done{colors.RESET}",
        )

    def test_no_color_disables_ansi_for_tty(self):
        stream = FakeTty()
        environ = {"NO_COLOR": ""}

        self.assertFalse(colors.supports_color(stream=stream, environ=environ))
        self.assertEqual(colors.bold("title", stream=stream, environ=environ), "title")

    def test_force_color_enables_ansi_for_non_tty_and_overrides_no_color(self):
        stream = io.StringIO()
        environ = {"FORCE_COLOR": "1", "NO_COLOR": "1"}

        self.assertTrue(colors.supports_color(stream=stream, environ=environ))
        self.assertEqual(
            colors.red("error", stream=stream, environ=environ),
            f"{colors.RED}error{colors.RESET}",
        )

    def test_force_color_zero_explicitly_disables_ansi(self):
        stream = FakeTty()

        self.assertFalse(
            colors.supports_color(stream=stream, environ={"FORCE_COLOR": "0"})
        )

    def test_terminal_text_escapes_controls_and_invalid_filename_bytes(self):
        value = "repo\x1b[2J\nnext\r\t\x00\x9b\udcff\u202e\u2028"

        sanitized = colors.safe_terminal_text(value)

        self.assertEqual(
            sanitized,
            r"repo\x1b[2J\nnext\r\t\x00\x9b\xff\u202e\u2028",
        )
        self.assertTrue(all(
            ord(character) >= 0x20 and not 0x7F <= ord(character) <= 0x9F
            for character in sanitized
        ))

    def test_multiline_text_preserves_layout_but_escapes_controls(self):
        value = "line\n\tvalue\x1b\r\u2066"

        self.assertEqual(
            colors.safe_multiline_text(value),
            "line\n\tvalue" + r"\x1b\r\u2066",
        )


if __name__ == "__main__":
    unittest.main()
