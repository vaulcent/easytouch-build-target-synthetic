"""Authoritative ERP behavior evidence for the Lead "Expected Deal Value" custom field.

This module is executed twice:
  1. Locally (python3 -m unittest discover -s tests -v) where Frappe is not
     installed -> the Frappe-backed cases are skipped via skipUnless.
  2. Via `bench execute` against a disposable ERPNext v16 validation site,
     where it must actually exercise real Frappe metadata and a real Lead
     document.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe
    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


def _ensure_site_context():
    """Reuse the active Frappe db context set up by `bench execute` when
    present; only fall back to initializing from frappe.local.site."""
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

    @classmethod
    def setUpClass(cls):
        _ensure_site_context()
        frappe.set_user("Administrator")
        cls._created_custom_field = False
        cls._created_test_lead_name = None

        with open(FIXTURE_PATH) as f:
            cls.fixture_entries = json.load(f)

        cls.lead_entry = next(
            e for e in cls.fixture_entries
            if e["dt"] == "Lead" and e["fieldname"] == "expected_deal_value"
        )

        existing = frappe.db.exists("Custom Field", cls.lead_entry["name"])
        if not existing:
            doc = frappe.get_doc({
                "doctype": "Custom Field",
                "dt": cls.lead_entry["dt"],
                "fieldname": cls.lead_entry["fieldname"],
                "fieldtype": cls.lead_entry["fieldtype"],
                "label": cls.lead_entry["label"],
                "insert_after": cls.lead_entry["insert_after"],
            })
            doc.insert(ignore_permissions=True)
            cls._created_custom_field = True

        frappe.clear_cache(doctype="Lead")
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        if cls._created_test_lead_name and frappe.db.exists("Lead", cls._created_test_lead_name):
            frappe.delete_doc(
                "Lead", cls._created_test_lead_name, ignore_permissions=True, force=True
            )
        if cls._created_custom_field:
            name = cls.lead_entry["name"]
            if frappe.db.exists("Custom Field", name):
                frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
        frappe.clear_cache(doctype="Lead")
        frappe.db.commit()

    def test_exactly_one_currency_custom_field_installed(self):
        rows = frappe.get_all(
            "Custom Field",
            filters={"dt": "Lead", "fieldname": "expected_deal_value"},
            fields=["name", "fieldtype", "label", "insert_after"],
        )
        self.assertEqual(
            len(rows), 1,
            "Expected exactly one Custom Field row for Lead.expected_deal_value",
        )
        row = rows[0]
        self.assertEqual(row.fieldtype, "Currency")
        self.assertEqual(row.label, "Expected Deal Value")
        self.assertEqual(row.insert_after, "annual_revenue")

    def test_rendered_order_immediately_after_annual_revenue(self):
        meta = frappe.get_meta("Lead")
        fieldnames = [df.fieldname for df in meta.fields]
        idx_anchor = fieldnames.index("annual_revenue")
        idx_target = fieldnames.index("expected_deal_value")
        self.assertEqual(
            idx_target,
            idx_anchor + 1,
            "expected_deal_value must render directly after annual_revenue",
        )

    def test_no_other_field_shares_the_annual_revenue_anchor(self):
        rows = frappe.get_all(
            "Custom Field",
            filters={"dt": "Lead", "insert_after": "annual_revenue"},
            fields=["fieldname"],
        )
        fieldnames = {r.fieldname for r in rows}
        self.assertEqual(
            fieldnames,
            {"expected_deal_value"},
            "Only expected_deal_value may anchor to annual_revenue",
        )

    def test_value_persists_on_a_real_lead_record(self):
        # Insert a real Lead document with the custom field populated.
        lead = frappe.get_doc({
            "doctype": "Lead",
            "lead_name": "Easytouch QA Expected Deal Value Lead",
            "email_id": "qa.expected.deal.value@example.test",
            "expected_deal_value": 12345.67,
        })
        lead.insert(ignore_permissions=True)
        self.__class__._created_test_lead_name = lead.name
        frappe.db.commit()

        # Reload the in-memory document from the database to prove the
        # value was actually persisted, not merely held in memory.
        lead.reload()
        self.assertEqual(float(lead.expected_deal_value), 12345.67)

        # Independently fetch a fresh document instance for the same name
        # as a second, separate persistence proof.
        refetched = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(refetched.expected_deal_value), 12345.67)


if __name__ == "__main__":
    unittest.main()
