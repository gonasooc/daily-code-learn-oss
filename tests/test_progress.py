import io
import os
import unittest
from unittest.mock import patch

from lib.progress import ProgressDisplay


class FakeTty(io.StringIO):
    def isatty(self):
        return True


class ProgressDisplayTests(unittest.TestCase):
    def test_update_escapes_untrusted_status_and_project_controls(self):
        stream = FakeTty()
        with patch("lib.progress.sys.stderr", stream), \
                patch.dict(os.environ, {"NO_COLOR": ""}, clear=False):
            progress = ProgressDisplay(1)
            progress.update("repo\x1b[2J\nforged", "collecting\rhidden")

        output = stream.getvalue()
        self.assertEqual(output.count("\x1b"), 1)
        self.assertEqual(output.count("\r"), 1)
        self.assertIn(r"collecting\rhidden", output)
        self.assertIn(r"repo\x1b[2J\nforged", output)


if __name__ == "__main__":
    unittest.main()
