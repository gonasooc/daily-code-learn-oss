import os
import tempfile
import unittest

from lib.missed_days import _has_report


class MissedDaysReportDetectionTests(unittest.TestCase):
    def test_analysis_files_do_not_count_as_project_reports(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            for name in ("analysis.md", "codex-analysis.md", "claude-analysis.md"):
                with open(os.path.join(report_dir, name), "w", encoding="utf-8") as f:
                    f.write("# analysis\n")

            self.assertFalse(_has_report(output_dir, "2026-06-28"))

    def test_project_markdown_counts_as_report(self):
        with tempfile.TemporaryDirectory() as output_dir:
            report_dir = os.path.join(output_dir, "2026-06-28")
            os.makedirs(report_dir)
            with open(os.path.join(report_dir, "sample-app.md"), "w", encoding="utf-8") as f:
                f.write("# report\n")

            self.assertTrue(_has_report(output_dir, "2026-06-28"))


if __name__ == "__main__":
    unittest.main()
