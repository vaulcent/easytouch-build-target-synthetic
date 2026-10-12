"""Evidence for the "Lead Custom Field" requirement: add a custom
Currency field called "Expected Deal Value" to Lead, placed below
Annual Revenue.

Two layers of evidence live in this single dedicated module:

1. Static fixture-shape checks (always run): the Custom Field fixture
   entry exists exactly once, with the exact dt/fieldname/label/
   fieldtype/insert_after, and no other fixture entries are disturbed.

2. ``TestLeadExpectedDealValueCustomFieldBehavior``: the authoritative
   ERPNext v16 behavior evidence, proving -- against a real disposable
   ERPNext v16 site, after the fixture has actually been imported --
   that the live "Lead" DocType meta really carries a field named
   ``expected_deal_value`` with DocType "Lead", label
   "Expected Deal Value", fieldtype "Currency", and that the underlying
   Custom Field record's ``insert_after`` is exactly "annual_revenue"
   (i.e. it sits below Annual Revenue), and that it is settable/
   readable on a real Lead document.

Loaded by ``bench execute`` with an active Frappe database context:
reuses ``frappe.local.db`` when already present, and only initializes
from ``frappe.local.site`` when needed. The authoritative class skips
only when Frappe itself is unavailable in this local coding sandbox.
"""

from __future__ import annotations

import importlib.util
import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)

FRAPPE_AVAILABLE = importlib.util.find_spec("frappe") is not None


class TestLeadExpectedDealValueCustomFieldFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == "Lead"
            and entry.get("fieldname") == "expected_deal_value"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_expected_deal_value_field_exists_exactly_once(self):
        entries = self._entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Expected Deal Value' Custom Field "
            "fixture for Lead (idempotent - no duplicates).",
        )

    def test_expected_deal_value_field_definition(self):
        entry = self._entries()[0]
        self.assertEqual(entry["name"], "Lead-expected_deal_value")
        self.assertEqual(entry["dt"], "Lead")
        self.assertEqual(entry["fieldname"], "expected_deal_value")
        self.assertEqual(entry["fieldtype"], "Currency")
        self.assertEqual(entry["label"], "Expected Deal Value")
        self.assertEqual(entry["insert_after"], "annual_revenue")

    def test_existing_lead_fields_and_other_doctypes_untouched(self):
        for dt, fieldname in [
            ("Issue", "synthetic_reference"),
            ("Lead", "referral_source"),
            ("Lead", "potential_value"),
            ("Customer", "risk_classification"),
            ("Task", "priority_tier"),
            ("Opportunity", "release_pipeline_proof"),
            ("Item", "is_important_item"),
            ("Project", "sales_invoice"),
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


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; this authoritative "
    "case must run inside a real disposable ERPNext v16 site via "
    "bench execute.",
)
class TestLeadExpectedDealValueCustomFieldBehavior(unittest.TestCase):
    LEAD_EMAIL = "easytouch-expected-deal-value-test-lead@example.test"

    @classmethod
    def setUpClass(cls):
        import frappe

        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        cls.frappe = frappe
        frappe.set_user("Administrator")

    @classmethod
    def tearDownClass(cls):
        cls.frappe.set_user("Administrator")

    def test_field_exists_on_live_lead_meta_with_exact_shape(self):
        frappe = self.frappe
        meta = frappe.get_meta("Lead")
        docfield = meta.get_field("expected_deal_value")
        self.assertIsNotNone(
            docfield,
            "The 'expected_deal_value' field must exist on the live Lead "
            "DocType meta after fixture import.",
        )
        self.assertEqual(docfield.fieldtype, "Currency")
        self.assertEqual(docfield.label, "Expected Deal Value")

    def test_custom_field_record_insert_after_is_annual_revenue(self):
        frappe = self.frappe
        self.assertTrue(
            frappe.db.exists("Custom Field", "Lead-expected_deal_value"),
            "The live Custom Field record 'Lead-expected_deal_value' must "
            "exist after fixture import.",
        )
        custom_field = frappe.get_doc("Custom Field", "Lead-expected_deal_value")
        self.assertEqual(custom_field.dt, "Lead")
        self.assertEqual(custom_field.fieldname, "expected_deal_value")
        self.assertEqual(custom_field.label, "Expected Deal Value")
        self.assertEqual(custom_field.fieldtype, "Currency")
        self.assertEqual(
            custom_field.insert_after,
            "annual_revenue",
            "The field must be placed directly below Annual Revenue.",
        )

    def test_field_is_settable_and_readable_on_a_real_lead_document(self):
        frappe = self.frappe
        if frappe.db.exists("Lead", {"email_id": self.LEAD_EMAIL}):
            frappe.delete_doc(
                "Lead",
                frappe.db.get_value("Lead", {"email_id": self.LEAD_EMAIL}, "name"),
                force=True,
            )

        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Easytouch Expected Deal Value Test Lead",
                "email_id": self.LEAD_EMAIL,
                "annual_revenue": 500000,
                "expected_deal_value": 12345,
            }
        )
        lead.insert(ignore_permissions=True)
        frappe.db.commit()

        reloaded = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(reloaded.expected_deal_value), 12345.0)
        self.assertEqual(float(reloaded.annual_revenue), 500000.0)


if __name__ == "__main__":
    unittest.main()
