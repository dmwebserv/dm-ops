"""
Unit tests for the pure date-stamp parsing logic in
scripts/clear_review_queue.py. No filesystem access - argparse/os.listdir
are exercised only inside main(), which these tests never call.
"""

import os
import sys
import unittest
from datetime import date

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from clear_review_queue import file_age_days  # noqa: E402


class TestFileAgeDays(unittest.TestCase):
    def test_computes_age_from_yyyy_mm_stamp_in_filename(self):
        today = date(2026, 8, 19)
        age = file_age_days("lwp-2026-06.md", today)
        expected = (today - date(2026, 6, 1)).days
        self.assertEqual(age, expected)

    def test_returns_none_when_no_date_stamp_present(self):
        self.assertIsNone(file_age_days("notes.md", date(2026, 8, 19)))

    def test_returns_none_for_an_invalid_date_stamp(self):
        self.assertIsNone(file_age_days("report-9999-99.md", date(2026, 8, 19)))

    def test_zero_age_for_the_current_month(self):
        today = date(2026, 8, 19)
        age = file_age_days("business-competitors-2026-08.md", today)
        self.assertEqual(age, 18)


if __name__ == "__main__":
    unittest.main()
