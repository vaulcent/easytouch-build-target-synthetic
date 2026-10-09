import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)

EXPECTED_OPTIONS = ["Normal", "VIP", "High Risk"]


class TestCustomerRiskClassificationCustomField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _customer_risk_classification_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Customer"
            and entry.get("fieldname") == "risk_classification"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_risk_classification_field_exists_exactly_once(self):
        entries = self._customer_risk_classification_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Risk Classification' Custom Field fixture for "
            "Customer (idempotent - no duplicates).",
        )

    def test_risk_classification_field_definition(self):
        entry = self._customer_risk_classification_entries()[0]
        self.assertEqual(entry["label"], "Risk Classification")
        self.assertEqual(entry["fieldtype"], "Select")
        self.assertEqual(entry["dt"], "Customer")
        self.assertEqual(entry["name"], "Customer-risk_classification")
        self.assertEqual(entry["fieldname"], "risk_classification")
        self.assertEqual(entry["default"], "Normal")

    def test_risk_classification_options(self):
        entry = self._customer_risk_classification_entries()[0]
        options = entry["options"].split("\n")
        self.assertEqual(options, EXPECTED_OPTIONS)

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
