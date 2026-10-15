"""Authoritative ERP-behavior test for the Lead "Expected Deal Value" custom field.

This module is marked per the completion contract with EASYTOUCH_ERP_BEHAVIOR_KINDS.
It proves, against a real Frappe/ERPNext v16 site, that importing the
synthetic_build_target_app Custom Field fixtures results in a Currency field
named "Expected Deal Value" on the Lead DocType, positioned immediately after
the standard "annual_revenue" field.

The case is skipped only when Frappe itself is unavailable in this local
sandbox (it is intentionally unavailable here per the lab harness). It is not
skipped for any other reason, and it does not use SQLite or a mocked Frappe
as evidence.
"""

import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("CUSTOM_FIELD",)

try:
    import frappe  # type: ignore

    FRAPPE_AVAILABLE = True
except ImportError:
    frappe = None
    FRAPPE_AVAILABLE = False


APP_NAME = "synthetic_build_target_app"
TARGET_DOCTYPE = "Lead"
TARGET_FIELDNAME = "expected_deal_value"
TARGET_LABEL = "Expected Deal Value"
TARGET_FIELDTYPE = "Currency"
TARGET_INSERT_AFTER = "annual_revenue"


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is unavailable in this local sandbox; authoritative verification "
    "runs against a disposable ERPNext v16 site in the real validation lanes.",
)
class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    """Frappe-backed proof that the custom field fixture is correctly installed."""

    @classmethod
    def setUpClass(cls):
        site = os.environ.get("FRAPPE_SITE") or os.environ.get("SITE_NAME")
        if not site:
            raise unittest.SkipTest(
                "No FRAPPE_SITE/SITE_NAME configured for this sandbox; this "
                "module is intended to run against a disposable ERPNext v16 "
                "site in the authoritative validation lane."
            )
        frappe.init(site=site)
        frappe.connect()

    @classmethod
    def tearDownClass(cls):
        if FRAPPE_AVAILABLE:
            frappe.destroy()

    def test_fixture_installs_expected_custom_field(self):
        """Import fixtures, then confirm doctype/label/fieldtype/insert_after."""
        from frappe.modules.import_file import import_file_by_path

        fixture_path = frappe.get_app_path(
            APP_NAME, "fixtures", "custom_field.json"
        )
        import_file_by_path(fixture_path, force=True)
        frappe.db.commit()

        name = f"{TARGET_DOCTYPE}-{TARGET_FIELDNAME}"
        self.assertTrue(
            frappe.db.exists("Custom Field", name),
            "Expected Custom Field record was not created by fixture import.",
        )

        cf = frappe.get_doc("Custom Field", name)
        self.assertEqual(cf.dt, TARGET_DOCTYPE)
        self.assertEqual(cf.fieldname, TARGET_FIELDNAME)
        self.assertEqual(cf.label, TARGET_LABEL)
        self.assertEqual(cf.fieldtype, TARGET_FIELDTYPE)
        self.assertEqual(cf.insert_after, TARGET_INSERT_AFTER)

        meta = frappe.get_meta(TARGET_DOCTYPE)
        field = meta.get_field(TARGET_FIELDNAME)
        self.assertIsNotNone(
            field, "Expected Deal Value field is not visible on Lead meta."
        )
        self.assertEqual(field.label, TARGET_LABEL)
        self.assertEqual(field.fieldtype, TARGET_FIELDTYPE)
        self.assertEqual(field.insert_after, TARGET_INSERT_AFTER)

    def test_field_accepts_currency_value_on_a_lead(self):
        """Idempotent proof: create/update a Lead and round-trip the value."""
        lead_name = frappe.db.get_value(
            "Lead", {"lead_name": "Nasiib Expected Deal Value Probe"}, "name"
        )
        if not lead_name:
            lead = frappe.get_doc(
                {
                    "doctype": "Lead",
                    "lead_name": "Nasiib Expected Deal Value Probe",
                    "expected_deal_value": 12345.67,
                }
            )
            lead.insert(ignore_permissions=True)
            lead_name = lead.name
        else:
            lead = frappe.get_doc("Lead", lead_name)
            lead.expected_deal_value = 12345.67
            lead.save(ignore_permissions=True)

        frappe.db.commit()

        stored = frappe.db.get_value("Lead", lead_name, "expected_deal_value")
        self.assertEqual(float(stored), 12345.67)


if __name__ == "__main__":
    unittest.main()
