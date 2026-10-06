import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


class TestCustomerSupportReferenceCodeCustomField(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _matching_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Customer"
            and entry.get("fieldname") == "support_reference_code"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_support_reference_code_field_exists_exactly_once(self):
        entries = self._matching_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Support Reference Code' Custom Field fixture "
            "for Customer (idempotent - no duplicates).",
        )

    def test_support_reference_code_field_definition(self):
        entry = self._matching_entries()[0]
        self.assertEqual(entry["doctype"], "Custom Field")
        self.assertEqual(entry["dt"], "Customer")
        self.assertEqual(entry["fieldname"], "support_reference_code")
        self.assertEqual(entry["fieldtype"], "Data")
        self.assertEqual(entry["label"], "Support Reference Code")
        self.assertEqual(entry["insert_after"], "customer_name")

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
