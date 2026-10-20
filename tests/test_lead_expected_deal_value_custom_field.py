"""Authoritative ERP behavior test for the Lead "Expected Deal Value" custom field.

This module is the marked authoritative suite for the custom_field change that adds
a Currency Custom Field named "Expected Deal Value" (fieldname expected_deal_value)
to the Lead DocType, placed directly after the standard annual_revenue field.

It is loaded by `bench execute` with an active Frappe database context inside a
disposable ERPNext v16 validation site. Locally (no Frappe installed) the single
ERP-backed test case is skipped via skipUnless; it must execute for real once Frappe
is available.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe  # noqa: F401
    HAS_FRAPPE = True
except ImportError:
    HAS_FRAPPE = False


FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


def _load_fixture_entry():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
        entries = json.load(fh)
    for entry in entries:
        if entry.get("dt") == "Lead" and entry.get("fieldname") == "expected_deal_value":
            return entry
    raise AssertionError("expected_deal_value fixture entry for Lead not found")


class TestLeadFixtureShape(unittest.TestCase):
    """Non-ERP sanity check that the fixture file itself is well formed."""

    def test_fixture_declares_expected_field(self):
        entry = _load_fixture_entry()
        self.assertEqual(entry["doctype"], "Custom Field")
        self.assertEqual(entry["dt"], "Lead")
        self.assertEqual(entry["fieldname"], "expected_deal_value")
        self.assertEqual(entry["fieldtype"], "Currency")
        self.assertEqual(entry["label"], "Expected Deal Value")
        self.assertEqual(entry["insert_after"], "annual_revenue")


@unittest.skipUnless(HAS_FRAPPE, "Frappe is not available in this local sandbox")
class TestLeadExpectedDealValueErpBehavior(unittest.TestCase):
    """Real ERPNext v16 behavior evidence (runs inside bench execute only)."""

    @classmethod
    def setUpClass(cls):
        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        entry = _load_fixture_entry()
        if not frappe.db.exists("Custom Field", entry["name"]):
            doc = frappe.get_doc({
                "doctype": "Custom Field",
                "dt": entry["dt"],
                "fieldname": entry["fieldname"],
                "fieldtype": entry["fieldtype"],
                "label": entry["label"],
                "insert_after": entry["insert_after"],
            })
            doc.insert(ignore_permissions=True)
            frappe.db.commit()

        frappe.clear_cache(doctype="Lead")

    def setUp(self):
        self._created_lead_names = []

    def tearDown(self):
        for name in self._created_lead_names:
            if frappe.db.exists("Lead", name):
                frappe.delete_doc("Lead", name, force=True, ignore_permissions=True)
        if self._created_lead_names:
            frappe.db.commit()

    def test_custom_field_metadata_and_render_order(self):
        meta = frappe.get_meta("Lead", cached=False)
        field = meta.get_field("expected_deal_value")

        self.assertIsNotNone(field, "expected_deal_value field missing from Lead meta")
        self.assertEqual(field.fieldtype, "Currency")
        self.assertEqual(field.label, "Expected Deal Value")
        self.assertEqual(field.insert_after, "annual_revenue")

        fieldnames_in_order = [df.fieldname for df in meta.fields]
        self.assertIn("annual_revenue", fieldnames_in_order)
        self.assertIn("expected_deal_value", fieldnames_in_order)

        anchor_index = fieldnames_in_order.index("annual_revenue")
        target_index = fieldnames_in_order.index("expected_deal_value")
        self.assertEqual(
            target_index,
            anchor_index + 1,
            "expected_deal_value must render immediately after annual_revenue",
        )

    def test_value_persists_on_real_lead_document(self):
        # Insert a real Lead document with the custom field populated.
        lead = frappe.get_doc({
            "doctype": "Lead",
            "lead_name": "Easytouch Expected Deal Value Test Lead",
            "first_name": "Easytouch",
            "company_name": "Easytouch QA Co",
            "status": "Lead",
            "expected_deal_value": 12345.67,
        })
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        self._created_lead_names.append(lead.name)

        # Prove persistence by reloading the in-memory document from the database.
        lead.reload()
        self.assertEqual(float(lead.expected_deal_value), 12345.67)

        # Prove persistence a second way: fetch a brand-new document instance by name.
        reloaded = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(reloaded.expected_deal_value), 12345.67)

        # Prove persistence a third way: read the raw column value directly from the DB.
        db_value = frappe.db.get_value("Lead", lead.name, "expected_deal_value")
        self.assertEqual(float(db_value), 12345.67)


if __name__ == "__main__":
    unittest.main()
