import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


class TestOpportunityReleasePipelineProofCustomField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _release_pipeline_proof_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Opportunity"
            and entry.get("fieldname") == "release_pipeline_proof"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_release_pipeline_proof_field_exists_exactly_once(self):
        entries = self._release_pipeline_proof_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Release Pipeline Proof' Custom Field fixture "
            "for Opportunity (idempotent - no duplicates).",
        )

    def test_release_pipeline_proof_field_definition(self):
        entry = self._release_pipeline_proof_entries()[0]
        self.assertEqual(entry["label"], "Release Pipeline Proof")
        self.assertEqual(entry["fieldtype"], "Small Text")
        self.assertEqual(entry["dt"], "Opportunity")
        self.assertEqual(entry["name"], "Opportunity-release_pipeline_proof")
        self.assertEqual(entry["fieldname"], "release_pipeline_proof")

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
        self.assertEqual(len(issue_entries), 1)
        self.assertEqual(len(lead_entries), 1)
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
