import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)

EXPECTED_OPTIONS = ["Website", "Referral", "Cold Call"]


class TestLeadReferralSourceCustomField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _lead_referral_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Lead"
            and entry.get("fieldname") == "referral_source"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_referral_source_field_exists_exactly_once(self):
        entries = self._lead_referral_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Referral Source' Custom Field fixture for Lead "
            "(idempotent - no duplicates).",
        )

    def test_referral_source_field_definition(self):
        entry = self._lead_referral_entries()[0]
        self.assertEqual(entry["label"], "Referral Source")
        self.assertEqual(entry["fieldtype"], "Select")
        self.assertEqual(entry["dt"], "Lead")

    def test_referral_source_options(self):
        entry = self._lead_referral_entries()[0]
        options = entry["options"].split("\n")
        self.assertEqual(options, EXPECTED_OPTIONS)

    def test_existing_issue_custom_field_untouched(self):
        issue_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Issue"
            and entry.get("fieldname") == "synthetic_reference"
        ]
        self.assertEqual(len(issue_entries), 1)
        self.assertEqual(issue_entries[0]["fieldtype"], "Data")

    def test_no_duplicate_dt_fieldname_pairs_overall(self):
        seen = set()
        for entry in self.fixtures:
            key = (entry.get("dt"), entry.get("fieldname"))
            self.assertNotIn(
                key, seen, f"Duplicate Custom Field fixture detected for {key}"
            )
            seen.add(key)


if __name__ == "__main__":
    unittest.main()
