"""
Unit tests for the pure text-processing helpers in scripts/competitor_check.py:
slug generation, HTML-to-readable-lines reduction, boilerplate noise
filtering, and the order-independent line diff. No network calls.
"""

import os
import sys
import unittest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from competitor_check import slugify, page_to_lines, is_noise, readable_lines, diff_lines  # noqa: E402


class TestSlugify(unittest.TestCase):
    def test_lowercases_and_hyphenates(self):
        self.assertEqual(slugify("RIOT Studio"), "riot-studio")

    def test_strips_punctuation(self):
        self.assertEqual(slugify("Patrick Stephen Ltd."), "patrick-stephen-ltd")

    def test_collapses_repeated_separators(self):
        self.assertEqual(slugify("A   B---C"), "a-b-c")

    def test_falls_back_when_nothing_left(self):
        self.assertEqual(slugify("***"), "competitor")


class TestPageToLines(unittest.TestCase):
    def test_splits_block_elements_onto_their_own_lines(self):
        html = "<h1>Title</h1><p>Body text here</p>"
        self.assertEqual(page_to_lines(html), ["Title", "Body text here"])

    def test_strips_script_and_style_content(self):
        html = "<style>.a{color:red}</style><p>Real content only</p><script>var x=1;</script>"
        self.assertEqual(page_to_lines(html), ["Real content only"])

    def test_unescapes_html_entities(self):
        html = "<p>Fish &amp; chips</p>"
        self.assertEqual(page_to_lines(html), ["Fish & chips"])

    def test_collapses_internal_whitespace(self):
        html = "<p>Too    many   spaces</p>"
        self.assertEqual(page_to_lines(html), ["Too many spaces"])


class TestIsNoise(unittest.TestCase):
    def test_short_lines_are_noise(self):
        self.assertTrue(is_noise("Home"))

    def test_copyright_lines_are_noise(self):
        self.assertTrue(is_noise("© 2024 All rights reserved by the company"))

    def test_cookie_banner_lines_are_noise(self):
        self.assertTrue(is_noise("Accept all cookies to improve your experience"))

    def test_lines_starting_with_a_number_are_noise(self):
        self.assertTrue(is_noise("2024 was a great year for the business"))

    def test_real_sentence_is_not_noise(self):
        self.assertFalse(is_noise("We now offer full exterior painting services in Colchester"))


class TestReadableLines(unittest.TestCase):
    def test_filters_noise_and_deduplicates(self):
        html = (
            "<footer>© 2024 Some Studio</footer>"
            "<p>We offer high quality decorating services locally</p>"
            "<p>We offer high quality decorating services locally</p>"
        )
        self.assertEqual(
            readable_lines(html),
            ["We offer high quality decorating services locally"],
        )


class TestDiffLines(unittest.TestCase):
    def test_detects_additions_and_removals(self):
        old = ["Line A long enough to count", "Line B long enough to count"]
        new = ["Line A long enough to count", "Line C long enough to count"]
        added, removed = diff_lines(old, new)
        self.assertEqual(added, ["Line C long enough to count"])
        self.assertEqual(removed, ["Line B long enough to count"])

    def test_reordering_alone_produces_no_diff(self):
        old = ["First line here", "Second line here"]
        new = ["Second line here", "First line here"]
        added, removed = diff_lines(old, new)
        self.assertEqual(added, [])
        self.assertEqual(removed, [])

    def test_no_changes_when_identical(self):
        lines = ["Same content on both sides of the diff"]
        added, removed = diff_lines(lines, lines)
        self.assertEqual((added, removed), ([], []))


if __name__ == "__main__":
    unittest.main()
