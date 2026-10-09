import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


class TestLeadPotentialValueCustomField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _lead_potential_value_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Lead"
            and entry.get("fieldname") == "potential_value"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_potential_value_field_exists_exactly_once(self):
        entries = self._lead_potential_value_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Potential Value' Custom Field fixture for Lead "
            "(idempotent - no duplicates).",
        )

    def test_potential_value_field_definition(self):
        entry = self._lead_potential_value_entries()[0]
        self.assertEqual(entry["label"], "Potential Value")
        self.assertEqual(entry["fieldtype"], "Currency")
        self.assertEqual(entry["dt"], "Lead")
        self.assertEqual(entry["name"], "Lead-potential_value")

    def test_potential_value_insert_after_is_set(self):
        entry = self._lead_potential_value_entries()[0]
        self.assertEqual(entry["insert_after"], "annual_revenue")

    def test_existing_lead_referral_source_and_other_fields_untouched(self):
        referral_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Lead"
            and entry.get("fieldname") == "referral_source"
        ]
        issue_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Issue"
            and entry.get("fieldname") == "synthetic_reference"
        ]
        task_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Task"
            and entry.get("fieldname") == "priority_tier"
        ]
        self.assertEqual(len(referral_entries), 1)
        self.assertEqual(len(issue_entries), 1)
        self.assertEqual(len(task_entries), 1)

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
