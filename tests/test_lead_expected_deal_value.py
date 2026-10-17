"""Authoritative ERP behavior evidence for the Lead "Expected Deal Value" custom field.

This module is loaded both by the local sandbox (`python3 -m unittest discover`,
where Frappe is intentionally unavailable and the cases skip) and by the
disposable ERPNext v16 validation site via `bench execute`, where it must
actually exercise real Frappe metadata and a real Lead document.
"""

import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe  # type: ignore
    FRAPPE_AVAILABLE = True
except Exception:  # pragma: no cover - expected in the local coding sandbox
    FRAPPE_AVAILABLE = False


def _ensure_frappe_context():
    """Reuse an already-initialized Frappe db context (bench execute), or
    initialize one from frappe.local.site if a db connection is not yet
    present. Never requires a custom site-name environment variable."""
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local coding sandbox")
class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    """Marked ERP behavior test (custom_field) run inside a real disposable
    ERPNext v16 site. Proves the exact Custom Field metadata, its rendered
    position immediately after Annual Revenue, and that a value set on a
    real Lead persists through insert + reload."""

    @classmethod
    def setUpClass(cls):
        _ensure_frappe_context()
        if not getattr(frappe.local, "db", None):
            raise unittest.SkipTest("No active Frappe db context available")
        frappe.set_user("Administrator")
        cls._created_lead_name = None

    @classmethod
    def tearDownClass(cls):
        if cls._created_lead_name and frappe.db.exists("Lead", cls._created_lead_name):
            frappe.delete_doc("Lead", cls._created_lead_name, force=True, ignore_permissions=True)
            frappe.db.commit()

    def test_custom_field_metadata_is_exact(self):
        cf_name = frappe.db.get_value(
            "Custom Field",
            {"dt": "Lead", "fieldname": "expected_deal_value"},
            "name",
        )
        self.assertTrue(cf_name, "Custom Field Lead-expected_deal_value was not installed")

        cf = frappe.get_doc("Custom Field", cf_name)
        self.assertEqual(cf.dt, "Lead")
        self.assertEqual(cf.fieldtype, "Currency")
        self.assertEqual(cf.label, "Expected Deal Value")
        self.assertEqual(cf.fieldname, "expected_deal_value")
        self.assertEqual(cf.insert_after, "annual_revenue")

        # Exactly one such Custom Field exists on Lead.
        count = frappe.db.count(
            "Custom Field", {"dt": "Lead", "fieldname": "expected_deal_value"}
        )
        self.assertEqual(count, 1)

    def test_rendered_order_is_immediately_after_annual_revenue(self):
        frappe.clear_cache(doctype="Lead")
        meta = frappe.get_meta("Lead")
        fieldnames = [df.fieldname for df in meta.fields]

        self.assertIn("annual_revenue", fieldnames)
        self.assertIn("expected_deal_value", fieldnames)

        annual_revenue_index = fieldnames.index("annual_revenue")
        expected_deal_value_index = fieldnames.index("expected_deal_value")

        self.assertEqual(
            expected_deal_value_index,
            annual_revenue_index + 1,
            "Expected Deal Value must render directly after Annual Revenue",
        )

    def test_value_persists_on_real_lead_record(self):
        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Easytouch Expected Deal Value Test Lead",
                "company_name": "Easytouch Expected Deal Value Test Co",
                "expected_deal_value": 12345.67,
            }
        )
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        type(self)._created_lead_name = lead.name

        # Prove persistence by reloading the same in-memory Document from the
        # database (not merely re-fetching a separate object), then re-read
        # it from a brand-new Document instance as a second, independent check.
        lead.reload()
        self.assertEqual(float(lead.expected_deal_value), 12345.67)

        independently_reloaded = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(independently_reloaded.expected_deal_value), 12345.67)


if __name__ == "__main__":
    unittest.main()
