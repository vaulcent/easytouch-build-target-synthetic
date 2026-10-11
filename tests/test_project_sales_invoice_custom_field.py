import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


class TestProjectSalesInvoiceCustomField(unittest.TestCase):
    """Fixture-shape checks for the Project-sales_invoice Custom Field.

    This field is what makes the auto-created Project (see
    sales_invoice_project.create_project_for_submitted_sales_invoice)
    idempotently linkable back to its originating submitted Sales
    Invoice. The real behavior (field actually appears on Project after
    fixture import, and the hook actually sets/reads it) is proved by the
    authoritative Frappe-backed automation test module, not here.
    """

    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _project_sales_invoice_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Project"
            and entry.get("fieldname") == "sales_invoice"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_sales_invoice_field_exists_exactly_once(self):
        entries = self._project_sales_invoice_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Sales Invoice' Custom Field fixture for "
            "Project (idempotent - no duplicates).",
        )

    def test_sales_invoice_field_definition(self):
        entry = self._project_sales_invoice_entries()[0]
        self.assertEqual(entry["name"], "Project-sales_invoice")
        self.assertEqual(entry["dt"], "Project")
        self.assertEqual(entry["fieldname"], "sales_invoice")
        self.assertEqual(entry["fieldtype"], "Link")
        self.assertEqual(entry["options"], "Sales Invoice")
        self.assertEqual(entry["label"], "Sales Invoice")
        self.assertEqual(entry["insert_after"], "project_name")

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
