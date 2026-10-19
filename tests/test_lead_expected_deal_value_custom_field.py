"""Authoritative ERP behavior evidence for the Lead "Expected Deal Value" custom field.

Requirement: Add a custom Currency field called Expected Deal Value to Lead and place it
directly below Annual Revenue.

This module is loaded by `bench execute` against a disposable ERPNext v16 site with an
active Frappe database context (frappe.local.db). When Frappe is unavailable in the local
coding sandbox, the ERP-backed cases are skipped via unittest.skipUnless; they must execute
for real inside the installed ERPNext validation site.
"""

import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe
    FRAPPE_AVAILABLE = True
except ImportError:
    frappe = None
    FRAPPE_AVAILABLE = False


def _ensure_db_context():
    """Reuse an already-initialized Frappe DB context, or init from frappe.local.site."""
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    """EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)"""

    @classmethod
    def setUpClass(cls):
        _ensure_db_context()
        frappe.set_user("Administrator")
        cls._created_lead_names = []

    @classmethod
    def tearDownClass(cls):
        for name in cls._created_lead_names:
            if frappe.db.exists("Lead", name):
                frappe.delete_doc("Lead", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_custom_field_metadata_is_exact(self):
        """Exactly one Currency Custom Field on Lead, correct label/fieldname/insert_after."""
        rows = frappe.get_all(
            "Custom Field",
            filters={"dt": "Lead", "fieldname": "expected_deal_value"},
            fields=["name", "fieldtype", "label", "insert_after", "dt"],
        )
        self.assertEqual(
            len(rows), 1,
            "Expected exactly one Custom Field named expected_deal_value on Lead",
        )
        row = rows[0]
        self.assertEqual(row["dt"], "Lead")
        self.assertEqual(row["fieldtype"], "Currency")
        self.assertEqual(row["label"], "Expected Deal Value")
        self.assertEqual(row["insert_after"], "annual_revenue")

        # No other custom field on Lead should share the same insert_after anchor.
        anchor_sharers = frappe.get_all(
            "Custom Field",
            filters={
                "dt": "Lead",
                "insert_after": "annual_revenue",
            },
            fields=["fieldname"],
        )
        anchor_fieldnames = {r["fieldname"] for r in anchor_sharers}
        self.assertEqual(
            anchor_fieldnames, {"expected_deal_value"},
            "Only expected_deal_value may use annual_revenue as insert_after",
        )

    def test_field_is_rendered_immediately_after_annual_revenue(self):
        """Real Frappe metadata: rendered field order places the field right after the anchor."""
        meta = frappe.get_meta("Lead")
        fieldnames = [df.fieldname for df in meta.fields]

        self.assertIn("annual_revenue", fieldnames)
        self.assertIn("expected_deal_value", fieldnames)

        anchor_idx = fieldnames.index("annual_revenue")
        target_idx = fieldnames.index("expected_deal_value")

        self.assertEqual(
            target_idx, anchor_idx + 1,
            "expected_deal_value must be rendered directly after annual_revenue, "
            f"got order: ...{fieldnames[anchor_idx:anchor_idx + 3]}...",
        )

        target_df = meta.get_field("expected_deal_value")
        self.assertEqual(target_df.fieldtype, "Currency")
        self.assertEqual(target_df.label, "Expected Deal Value")

    def test_value_persists_on_real_lead_record(self):
        """Insert and reload a real Lead; the Currency value must persist through the database."""
        lead = frappe.get_doc({
            "doctype": "Lead",
            "lead_name": "Easytouch QA Lead for Expected Deal Value",
            "email_id": "qa-lead-expected-deal-value@example.test",
            "annual_revenue": 50000,
            "expected_deal_value": 12345.67,
        })

        # Insert the real record into the disposable ERPNext v16 database.
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        self.__class__._created_lead_names.append(lead.name)

        # Mutate the in-memory object so reload() is proven to re-fetch from the database
        # rather than merely returning cached in-memory state.
        lead.expected_deal_value = 0
        lead.annual_revenue = 0

        # Reload the exact same document object directly from the database.
        lead.reload()

        self.assertEqual(float(lead.expected_deal_value), 12345.67)
        self.assertEqual(float(lead.annual_revenue), 50000)

        # Independently fetch a fresh document instance as corroborating evidence.
        refetched = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(refetched.expected_deal_value), 12345.67)
        self.assertEqual(float(refetched.annual_revenue), 50000)


if __name__ == "__main__":
    unittest.main()
