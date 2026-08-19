"""
Unit tests for the pure data-transformation and validation logic in
scripts/generate_report.py: summarising raw check history into a period
summary, and the hold-for-review anomaly rules.

Fully offline. generate_report.py reads ANTHROPIC_API_KEY at import time
(it's needed by drafting/QC, which this file never calls), so a dummy value
is set before import purely to satisfy that import - no API call is ever
made by these tests.
"""

import os
import sys
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used-by-these-tests")

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from generate_report import summarise, needs_human_review  # noqa: E402


class TestSummarise(unittest.TestCase):
    def test_returns_none_for_no_records(self):
        self.assertIsNone(summarise([]))

    def test_uptime_excludes_non_downtime_flags(self):
        # Broken links / SSL warnings are real issues but must NOT count
        # against uptime (KNOWLEDGE.md "lessons learned").
        records = [
            {"checked_at": "2026-01-01T00:00:00+00:00", "errors": ["2 broken link(s) found"], "response_time_ms": 100},
            {"checked_at": "2026-01-02T00:00:00+00:00", "errors": [], "response_time_ms": 200},
        ]
        summary = summarise(records)
        self.assertEqual(summary["uptime_pct"], 100.0)

    def test_uptime_counts_unreachable_and_server_errors_as_downtime(self):
        records = [
            {"checked_at": "2026-01-01T00:00:00+00:00", "errors": ["Site unreachable: timeout"], "response_time_ms": None},
            {"checked_at": "2026-01-02T00:00:00+00:00", "errors": ["Server error: 500"], "response_time_ms": None},
            {"checked_at": "2026-01-03T00:00:00+00:00", "errors": [], "response_time_ms": 150},
        ]
        summary = summarise(records)
        self.assertEqual(summary["uptime_pct"], round(1 / 3 * 100, 1))

    def test_average_response_time_ignores_missing_values(self):
        records = [
            {"checked_at": "2026-01-01T00:00:00+00:00", "errors": [], "response_time_ms": 100},
            {"checked_at": "2026-01-02T00:00:00+00:00", "errors": [], "response_time_ms": None},
            {"checked_at": "2026-01-03T00:00:00+00:00", "errors": [], "response_time_ms": 300},
        ]
        summary = summarise(records)
        self.assertEqual(summary["avg_response_ms"], 200)

    def test_ssl_days_left_uses_latest_available_value(self):
        records = [
            {"checked_at": "2026-01-01T00:00:00+00:00", "errors": [], "ssl_days_left": 80},
            {"checked_at": "2026-01-02T00:00:00+00:00", "errors": [], "ssl_days_left": 79},
        ]
        summary = summarise(records)
        self.assertEqual(summary["ssl_days_left_latest"], 79)

    def test_collects_all_issues_with_their_dates(self):
        records = [
            {"checked_at": "2026-01-05T00:00:00+00:00", "errors": ["No <form> tag detected on homepage"]},
        ]
        summary = summarise(records)
        self.assertEqual(
            summary["issues"],
            [{"date": "2026-01-05", "issue": "No <form> tag detected on homepage"}],
        )


class TestNeedsHumanReview(unittest.TestCase):
    def base_summary(self, **overrides):
        summary = {
            "checks_run": 30,
            "uptime_pct": 100.0,
            "ssl_days_left_latest": 80,
            "issues": [],
        }
        summary.update(overrides)
        return summary

    def test_no_reasons_for_a_clean_period(self):
        self.assertEqual(needs_human_review(self.base_summary()), [])

    def test_flags_thin_sample_size(self):
        reasons = needs_human_review(self.base_summary(checks_run=3))
        self.assertTrue(any("thin sample" in r for r in reasons))

    def test_flags_uptime_below_99_percent(self):
        reasons = needs_human_review(self.base_summary(uptime_pct=95.0))
        self.assertTrue(any("uptime dropped" in r for r in reasons))

    def test_flags_ssl_expiring_soon(self):
        reasons = needs_human_review(self.base_summary(ssl_days_left_latest=5))
        self.assertTrue(any("SSL expires" in r for r in reasons))

    def test_does_not_flag_ssl_when_comfortably_valid(self):
        reasons = needs_human_review(self.base_summary(ssl_days_left_latest=14))
        self.assertFalse(any("SSL expires" in r for r in reasons))

    def test_flags_high_issue_count(self):
        reasons = needs_human_review(self.base_summary(issues=[{"date": "x", "issue": "a"}] * 3))
        self.assertTrue(any("issues flagged" in r for r in reasons))

    def test_multiple_reasons_can_combine(self):
        reasons = needs_human_review(self.base_summary(checks_run=2, uptime_pct=90.0))
        self.assertEqual(len(reasons), 2)


if __name__ == "__main__":
    unittest.main()
