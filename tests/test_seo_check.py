"""
Unit tests for the pure HTML-parsing helpers in scripts/seo_check.py.
No network calls - these only operate on inline HTML strings.
"""

import os
import sys
import unittest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from seo_check import get_attr, find_meta_content  # noqa: E402


class TestGetAttr(unittest.TestCase):
    def test_extracts_double_quoted_attribute(self):
        self.assertEqual(get_attr('<meta name="description" content="Hello">', "content"), "Hello")

    def test_extracts_single_quoted_attribute(self):
        self.assertEqual(get_attr("<meta name='description' content='Hello'>", "content"), "Hello")

    def test_is_case_insensitive_on_attribute_name(self):
        self.assertEqual(get_attr('<meta NAME="description">', "name"), "description")

    def test_returns_none_when_attribute_missing(self):
        self.assertIsNone(get_attr('<meta name="description">', "content"))

    def test_strips_surrounding_whitespace(self):
        self.assertEqual(get_attr('<meta content="  padded  ">', "content"), "padded")

    def test_works_regardless_of_attribute_order(self):
        self.assertEqual(get_attr('<img src="x.jpg" alt="A dog">', "alt"), "A dog")
        self.assertEqual(get_attr('<img alt="A dog" src="x.jpg">', "alt"), "A dog")


class TestFindMetaContent(unittest.TestCase):
    def test_finds_content_regardless_of_attribute_order(self):
        html = '<meta content="A great site" name="description">'
        self.assertEqual(find_meta_content(html, "name", "description"), "A great site")

    def test_finds_property_based_og_tags(self):
        html = '<meta property="og:title" content="Home">'
        self.assertEqual(find_meta_content(html, "property", "og:title"), "Home")

    def test_match_value_is_case_insensitive(self):
        html = '<meta name="Description" content="Hi">'
        self.assertEqual(find_meta_content(html, "name", "description"), "Hi")

    def test_returns_none_when_no_matching_tag(self):
        html = '<meta name="viewport" content="width=device-width">'
        self.assertIsNone(find_meta_content(html, "name", "description"))

    def test_ignores_unrelated_meta_tags(self):
        html = '<meta charset="utf-8"><meta name="description" content="Real desc">'
        self.assertEqual(find_meta_content(html, "name", "description"), "Real desc")


if __name__ == "__main__":
    unittest.main()
