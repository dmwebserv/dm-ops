"""
Unit tests for the pure data-transformation logic in
scripts/generate_dashboard.py: revenue/MRR calculation, timestamp
humanising, state-to-colour mapping, HTML escaping, config flag reading,
and the "what needs attention" prioritisation. No network calls, no file
I/O - all functions here take plain data in and return plain data out.
"""

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from generate_dashboard import (  # noqa: E402
    compute_revenue,
    humanise_age,
    state_colour,
    esc,
    read_config_flags,
    build_attention,
)


class TestComputeRevenue(unittest.TestCase):
    def test_counts_only_care_plan_clients_towards_mrr(self):
        clients = [
            {"id": "a", "care_plan": True},
            {"id": "b", "care_plan": False},
            {"id": "c", "care_plan": True},
        ]
        result = compute_revenue(clients, {"care_plan_monthly_value": 30})
        self.assertEqual(result, {"care_plan_clients": 2, "total_clients": 3, "mrr": 60})

    def test_uses_default_care_plan_value_when_not_configured(self):
        clients = [{"id": "a", "care_plan": True}]
        result = compute_revenue(clients, {})
        self.assertEqual(result["mrr"], 30)


class TestHumaniseAge(unittest.TestCase):
    def test_returns_never_for_none(self):
        self.assertEqual(humanise_age(None), "never")

    def test_returns_unknown_for_unparseable_string(self):
        self.assertEqual(humanise_age("not-a-date"), "unknown")

    def test_formats_minutes_ago(self):
        when = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.assertEqual(humanise_age(when), "5m ago")

    def test_formats_hours_ago(self):
        when = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        self.assertEqual(humanise_age(when), "3h ago")

    def test_formats_days_ago(self):
        when = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        self.assertEqual(humanise_age(when), "4d ago")


class TestStateColour(unittest.TestCase):
    def test_known_states_map_to_expected_colours(self):
        self.assertEqual(state_colour("success"), "var(--live)")
        self.assertEqual(state_colour("failure"), "var(--stop)")

    def test_unknown_state_falls_back_to_idle(self):
        self.assertEqual(state_colour("something_new"), "var(--idle)")


class TestEsc(unittest.TestCase):
    def test_escapes_html_special_characters(self):
        self.assertEqual(
            esc('<a href="x">A & B</a>'),
            '&lt;a href="x"&gt;A &amp; B&lt;/a&gt;',
        )

    def test_handles_non_string_input(self):
        self.assertEqual(esc(42), "42")


class TestReadConfigFlags(unittest.TestCase):
    def test_reads_expected_keys_with_defaults(self):
        flags = read_config_flags({"test_mode": True, "force_send_for_testing": False})
        self.assertEqual(flags["test_mode"], True)
        self.assertEqual(flags["force_send"], False)
        self.assertEqual(flags["from_email"], "")
        self.assertEqual(flags["test_email"], "")


class TestBuildAttention(unittest.TestCase):
    def test_empty_when_everything_is_healthy(self):
        items = build_attention(
            health=[{"status": "ok", "ssl_days_left": 90, "errors": [], "name": "Site"}],
            seo=None,
            queue=[],
            flags={"test_mode": False, "force_send": False},
            runs={},
            competitors={"configured": False, "records": []},
        )
        self.assertEqual(items, [])

    def test_flags_test_mode_as_an_attention_item(self):
        items = build_attention(
            health=[], seo=None, queue=[],
            flags={"test_mode": True, "force_send": False},
            runs={}, competitors={"configured": False, "records": []},
        )
        self.assertTrue(any("Test mode is on" in i["label"] for i in items))

    def test_urgent_client_health_is_flagged(self):
        items = build_attention(
            health=[{"status": "urgent", "ssl_days_left": None, "errors": ["Site unreachable"], "name": "LWP"}],
            seo=None, queue=[],
            flags={"test_mode": False, "force_send": False},
            runs={}, competitors={"configured": False, "records": []},
        )
        self.assertTrue(any("needs urgent attention" in i["label"] for i in items))

    def test_review_queue_items_are_flagged(self):
        items = build_attention(
            health=[], seo=None, queue=[{"file": "a.md"}],
            flags={"test_mode": False, "force_send": False},
            runs={}, competitors={"configured": False, "records": []},
        )
        self.assertTrue(any("waiting for you to read" in i["label"] for i in items))

    def test_items_are_sorted_by_weight(self):
        items = build_attention(
            health=[{"status": "urgent", "ssl_days_left": None, "errors": ["down"], "name": "X"}],
            seo=None, queue=[{"file": "a.md"}],
            flags={"test_mode": True, "force_send": False},
            runs={}, competitors={"configured": False, "records": []},
        )
        weights = [i["weight"] for i in items]
        self.assertEqual(weights, sorted(weights))


if __name__ == "__main__":
    unittest.main()
