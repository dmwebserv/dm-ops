"""
Unit tests for the pure HTML-parsing helpers in scripts/check_sites.py.
No network calls - these only operate on inline HTML strings.
"""

import os
import sys
import unittest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from check_sites import extract_links, check_forms  # noqa: E402


class TestExtractLinks(unittest.TestCase):
    def test_resolves_relative_links_against_base_url(self):
        html = '<a href="/about">About</a>'
        links = extract_links(html, "https://example.co.uk")
        self.assertIn("https://example.co.uk/about", links)

    def test_skips_anchor_mailto_tel_and_javascript_links(self):
        html = (
            '<a href="#section">Jump</a>'
            '<a href="mailto:hi@example.co.uk">Email</a>'
            '<a href="tel:+441234567890">Call</a>'
            '<a href="javascript:void(0)">Nothing</a>'
        )
        links = extract_links(html, "https://example.co.uk")
        self.assertEqual(links, set())

    def test_keeps_absolute_links(self):
        html = '<a href="https://other.co.uk/page">Other</a>'
        links = extract_links(html, "https://example.co.uk")
        self.assertIn("https://other.co.uk/page", links)

    def test_deduplicates_links(self):
        html = '<a href="/a">A</a><a href="/a">A again</a>'
        links = extract_links(html, "https://example.co.uk")
        self.assertEqual(links, {"https://example.co.uk/a"})


class TestCheckForms(unittest.TestCase):
    def test_detects_a_single_form(self):
        result = check_forms('<form action="/submit"></form>')
        self.assertEqual(result, {"found": True, "count": 1})

    def test_detects_multiple_forms(self):
        result = check_forms('<form></form><form></form>')
        self.assertEqual(result, {"found": True, "count": 2})

    def test_reports_no_forms_found(self):
        result = check_forms('<div>No forms here</div>')
        self.assertEqual(result, {"found": False, "count": 0})

    def test_is_case_insensitive(self):
        result = check_forms('<FORM></FORM>')
        self.assertEqual(result, {"found": True, "count": 1})


if __name__ == "__main__":
    unittest.main()
