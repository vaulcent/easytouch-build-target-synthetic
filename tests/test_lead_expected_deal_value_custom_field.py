"""Authoritative ERP behavior evidence for the Lead "Expected Deal Value"
Custom Field requirement.

This module is intentionally dependency-free when Frappe is unavailable in
the local coding sandbox (it then skips), but it is designed to be loaded by
`bench execute` against a real, disposable ERPNext v16 validation site,
where Frappe IS available and the cases below execute for real against a
live database connection, a real DocType meta, and a real Lead document.
"""

import unittest

# Literal marker required by the completion contract. Only suites carrying
# this marker are treated as semantic ERP-behavior evidence.
EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe
    FRAPPE_AVAILABLE = True
except ImportError:  # pragma: no cover - expected in the local sandbox
    frappe = None
    FRAPPE_AVAILABLE = False


def _ensure_frappe_db_context():
    """Reuse an already-active Frappe db context (as under `bench execute`),
    only initializing/connecting from `frappe.local.site` when no active
    db context is already present.
    """
    if getattr(frappe.local, "db", None) is not None:
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    """Proves the Expected Deal Value Custom Field on Lead:
    - exists with the exact Currency fieldtype, label, fieldname, and
      insert_after anchor (annual_revenue), rendering directly after it, and
    - actually persists a real value across insert + reload of a Lead.
    """

    lead_name = None

    @classmethod
    def setUpClass(cls):
        _ensure_frappe_db_context()

    @classmethod
    def tearDownClass(cls):
        if cls.lead_name and frappe.db.exists("Lead", cls.lead_name):
            frappe.delete_doc("Lead", cls.lead_name, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_custom_field_metadata_and_rendered_order(self):
        meta = frappe.get_meta("Lead")
        field = meta.get_field("expected_deal_value")

        self.assertIsNotNone(field, "expected_deal_value field must exist on Lead")
        self.assertEqual(field.fieldtype, "Currency")
        self.assertEqual(field.label, "Expected Deal Value")
        self.assertEqual(field.fieldname, "expected_deal_value")
        self.assertEqual(field.insert_after, "annual_revenue")

        fieldnames = [df.fieldname for df in meta.fields]
        self.assertIn("annual_revenue", fieldnames)
        self.assertIn("expected_deal_value", fieldnames)

        anchor_idx = fieldnames.index("annual_revenue")
        self.assertEqual(
            fieldnames[anchor_idx + 1],
            "expected_deal_value",
            "expected_deal_value must be rendered directly after annual_revenue",
        )

    def test_value_persists_on_insert_and_reload(self):
        # Insert a real Lead with a real Expected Deal Value.
        lead = frappe.get_doc({
            "doctype": "Lead",
            "lead_name": "Easytouch Expected Deal Value Evidence Lead",
            "email_id": "easytouch.expected.deal.value.evidence@example.com",
            "expected_deal_value": 123456.78,
        })
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        type(self).lead_name = lead.name

        # Reload the same in-memory document from the database and verify
        # the value round-tripped through a real insert + reload cycle.
        lead.reload()
        self.assertEqual(float(lead.expected_deal_value), 123456.78)

        # Independently re-fetch a fresh document instance from the database
        # by name to further prove persistence beyond the in-memory object.
        refetched = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(refetched.expected_deal_value), 123456.78)


if __name__ == "__main__":
    unittest.main()
