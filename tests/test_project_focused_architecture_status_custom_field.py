import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


class TestProjectFocusedArchitectureStatusCustomField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _focused_architecture_status_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Project"
            and entry.get("fieldname") == "focused_architecture_status"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_focused_architecture_status_field_exists_exactly_once(self):
        entries = self._focused_architecture_status_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Focused Architecture Status' Custom Field "
            "fixture for Project (idempotent - no duplicates).",
        )

    def test_focused_architecture_status_field_definition(self):
        entry = self._focused_architecture_status_entries()[0]
        self.assertEqual(entry["label"], "Focused Architecture Status")
        self.assertEqual(entry["fieldtype"], "Data")
        self.assertEqual(entry["dt"], "Project")
        self.assertEqual(entry["name"], "Project-focused_architecture_status")
        self.assertEqual(entry["fieldname"], "focused_architecture_status")

    def test_existing_custom_fields_untouched(self):
        issue_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Issue"
            and entry.get("fieldname") == "synthetic_reference"
        ]
        lead_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Lead"
            and entry.get("fieldname") == "referral_source"
        ]
        task_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Task"
            and entry.get("fieldname") == "priority_tier"
        ]
        opportunity_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Opportunity"
            and entry.get("fieldname") == "release_pipeline_proof"
        ]
        self.assertEqual(len(issue_entries), 1)
        self.assertEqual(len(lead_entries), 1)
        self.assertEqual(len(task_entries), 1)
        self.assertEqual(len(opportunity_entries), 1)

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
