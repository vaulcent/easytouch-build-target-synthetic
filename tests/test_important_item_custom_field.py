import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


class TestImportantItemCustomField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _important_item_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Item"
            and entry.get("fieldname") == "important_item"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_important_item_field_exists_exactly_once(self):
        entries = self._important_item_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Important Item' Custom Field fixture for "
            "Item (idempotent - no duplicates).",
        )

    def test_important_item_field_definition(self):
        entry = self._important_item_entries()[0]
        self.assertEqual(entry["label"], "Important Item")
        self.assertEqual(entry["fieldtype"], "Check")
        self.assertEqual(entry["dt"], "Item")
        self.assertEqual(entry["name"], "Item-important_item")
        self.assertEqual(entry["insert_after"], "is_stock_item")

    def test_existing_custom_fields_untouched(self):
        risk_entries = [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Customer"
            and entry.get("fieldname") == "risk_classification"
        ]
        self.assertEqual(len(risk_entries), 1)

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
