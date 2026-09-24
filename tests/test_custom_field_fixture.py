"""Focused tests for the synthetic_reference Custom Field fixture.

These tests validate the fixture JSON directly (no Frappe runtime required),
matching the lightweight, dependency-free nature of this repository's checks.
"""

import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


class SyntheticReferenceCustomFieldTests(unittest.TestCase):
    def _load_fixture(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _get_synthetic_reference_field(self, fixtures):
        matches = [
            entry
            for entry in fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Issue"
            and entry.get("fieldname") == "synthetic_reference"
        ]
        self.assertEqual(
            len(matches),
            1,
            "Expected exactly one synthetic_reference Custom Field fixture entry.",
        )
        return matches[0]

    def test_fixture_file_is_valid_json_list(self):
        fixtures = self._load_fixture()
        self.assertIsInstance(fixtures, list)
        self.assertTrue(len(fixtures) >= 1)

    def test_synthetic_reference_field_has_expected_description(self):
        fixtures = self._load_fixture()
        field = self._get_synthetic_reference_field(fixtures)
        self.assertEqual(
            field.get("description"),
            "External reference used by support.",
        )

    def test_synthetic_reference_field_existing_behavior_preserved(self):
        fixtures = self._load_fixture()
        field = self._get_synthetic_reference_field(fixtures)
        # Existing behavior (fieldtype/label/target doctype) must remain unchanged.
        self.assertEqual(field.get("fieldtype"), "Data")
        self.assertEqual(field.get("label"), "Synthetic Reference")
        self.assertEqual(field.get("dt"), "Issue")


if __name__ == "__main__":
    unittest.main()
