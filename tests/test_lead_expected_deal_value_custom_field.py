"""Authoritative ERP behavior test for the Lead "Expected Deal Value" Custom Field.

This module is loaded by `bench execute` with an active Frappe database context on a
disposable ERPNext v16 validation site. It proves, against real Frappe metadata, that:

  * exactly one Currency Custom Field named "Expected Deal Value" exists on Lead with
    fieldname "expected_deal_value" and insert_after == "annual_revenue",
  * the rendered DocType field order places it immediately after annual_revenue, and
  * a real Lead document is inserted, reloaded, and the value persists.

Frappe is intentionally unavailable in the local coding sandbox, so these cases are
skipped there via unittest.skipUnless and must execute for real once this module is run
inside an installed ERPNext v16 site (reusing frappe.local.db when present).
"""

import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe  # noqa: F401
    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False


def _ensure_db_context():
    """Reuse an already-initialized Frappe DB context (bench execute), or init one."""
    if getattr(frappe.local, "db", None) is not None:
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    """EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',) authoritative suite."""

    @classmethod
    def setUpClass(cls):
        _ensure_db_context()
        cls._created_lead_names = []

    @classmethod
    def tearDownClass(cls):
        for name in cls._created_lead_names:
            if frappe.db.exists("Lead", name):
                frappe.delete_doc("Lead", name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_exactly_one_custom_field_installed_with_expected_metadata(self):
        matches = frappe.get_all(
            "Custom Field",
            filters={"dt": "Lead", "fieldname": "expected_deal_value"},
            fields=["name", "fieldtype", "label", "insert_after", "dt"],
        )
        self.assertEqual(
            len(matches), 1,
            "Expected exactly one Custom Field for Lead.expected_deal_value"
        )
        cf = matches[0]
        self.assertEqual(cf["dt"], "Lead")
        self.assertEqual(cf["fieldtype"], "Currency")
        self.assertEqual(cf["label"], "Expected Deal Value")
        self.assertEqual(cf["insert_after"], "annual_revenue")

    def test_no_other_custom_field_shares_the_annual_revenue_anchor(self):
        anchored = frappe.get_all(
            "Custom Field",
            filters={"dt": "Lead", "insert_after": "annual_revenue"},
            fields=["fieldname"],
        )
        fieldnames = {row["fieldname"] for row in anchored}
        self.assertEqual(
            fieldnames, {"expected_deal_value"},
            "Only expected_deal_value may anchor directly after annual_revenue on Lead"
        )

    def test_rendered_field_order_places_it_immediately_after_annual_revenue(self):
        meta = frappe.get_meta("Lead")
        fieldnames_in_order = [df.fieldname for df in meta.fields]
        self.assertIn("annual_revenue", fieldnames_in_order)
        self.assertIn("expected_deal_value", fieldnames_in_order)
        idx_anchor = fieldnames_in_order.index("annual_revenue")
        idx_new = fieldnames_in_order.index("expected_deal_value")
        self.assertEqual(
            idx_new, idx_anchor + 1,
            "expected_deal_value must be rendered directly after annual_revenue"
        )

        df = meta.get_field("expected_deal_value")
        self.assertEqual(df.fieldtype, "Currency")
        self.assertEqual(df.label, "Expected Deal Value")

    def test_value_persists_on_a_real_lead_record(self):
        # Insert a real Lead document with the new Currency field populated.
        lead = frappe.get_doc({
            "doctype": "Lead",
            "lead_name": "Easytouch Expected Deal Value Test Lead",
            "email_id": "expected-deal-value-test@example.test",
            "annual_revenue": 500000,
            "expected_deal_value": 125000,
        })
        lead.insert(ignore_permissions=True)
        self.__class__._created_lead_names.append(lead.name)
        frappe.db.commit()

        # Reload the in-memory document from the database (round-trip #1).
        lead.reload()
        self.assertEqual(lead.annual_revenue, 500000)
        self.assertEqual(lead.expected_deal_value, 125000)

        # Independently fetch a brand-new document instance for the same record
        # to prove the stored value survives a fresh load from the database,
        # not merely an in-memory reload (round-trip #2).
        reloaded = frappe.get_doc("Lead", lead.name)
        self.assertEqual(reloaded.annual_revenue, 500000)
        self.assertEqual(reloaded.expected_deal_value, 125000)

        # Mutate and persist again, then reload once more, to prove updates to
        # the new field actually round-trip through the database, not just the
        # original insert value.
        reloaded.expected_deal_value = 250000
        reloaded.save(ignore_permissions=True)
        frappe.db.commit()
        reloaded.reload()
        self.assertEqual(reloaded.expected_deal_value, 250000)


if __name__ == "__main__":
    unittest.main()
