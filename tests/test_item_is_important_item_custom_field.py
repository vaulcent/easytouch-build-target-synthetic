import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


class TestItemIsImportantItemCustomField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _is_important_item_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Item"
            and entry.get("fieldname") == "is_important_item"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_is_important_item_field_exists_exactly_once(self):
        entries = self._is_important_item_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Is Important Item' Custom Field fixture for "
            "Item (idempotent - no duplicates).",
        )

    def test_is_important_item_field_definition(self):
        entry = self._is_important_item_entries()[0]
        self.assertEqual(entry["label"], "Is Important Item")
        self.assertEqual(entry["fieldtype"], "Check")
        self.assertEqual(entry["dt"], "Item")
        self.assertEqual(entry["name"], "Item-is_important_item")
        self.assertEqual(entry["fieldname"], "is_important_item")
        self.assertEqual(entry.get("default"), "0")

    def test_existing_custom_fields_untouched(self):
        for dt, fieldname in [
            ("Issue", "synthetic_reference"),
            ("Lead", "referral_source"),
            ("Task", "priority_tier"),
            ("Opportunity", "release_pipeline_proof"),
        ]:
            entries = [
                entry
                for entry in self.fixtures
                if entry.get("doctype") == "Custom Field"
                and entry.get("dt") == dt
                and entry.get("fieldname") == fieldname
            ]
            self.assertEqual(len(entries), 1, f"Missing/duplicated {dt}.{fieldname}")

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
