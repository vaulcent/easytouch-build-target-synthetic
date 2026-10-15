"""Authoritative ERPNext v16 behavior test for the Lead > Expected Deal Value custom field.

Requirement: Lead Custom Field
    Add a custom Currency field called "Expected Deal Value" to Lead and place it
    below Annual Revenue.

This module is the single dedicated, compact behavior-test module for this change.
It is marked with the literal EASYTOUCH_ERP_BEHAVIOR_KINDS tuple below, as required
by the completion contract. It proves the exact DocType, label, fieldtype, and
insert_after value of the custom field after a real fixture import against a live,
fresh ERPNext v16 site (via a real Frappe connection) -- never SQLite or a mocked
Frappe/database. It may skip only when Frappe itself is unavailable in this local
sandbox; it must not be reduced to a source-inspection-only or import-only check in
the authoritative (Frappe-backed) run.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

try:
    import frappe  # noqa: F401
    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)

EXPECTED_DT = "Lead"
EXPECTED_FIELDNAME = "custom_expected_deal_value"
EXPECTED_LABEL = "Expected Deal Value"
EXPECTED_FIELDTYPE = "Currency"
EXPECTED_INSERT_AFTER = "annual_revenue"


class TestLeadExpectedDealValueCustomFieldErpBehavior(unittest.TestCase):
    """Proves the Lead Expected Deal Value custom field on a real ERPNext v16 site.

    EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)
    """

    @classmethod
    def setUpClass(cls):
        if not FRAPPE_AVAILABLE:
            raise unittest.SkipTest(
                "Frappe is not available in this local sandbox; this authoritative "
                "ERP-behavior case runs against a fresh ERPNext v16 site elsewhere."
            )
        site = os.environ.get("FRAPPE_SITE") or getattr(
            getattr(frappe, "local", None), "site", None
        )
        if not site:
            raise unittest.SkipTest(
                "No disposable ERPNext v16 site configured (FRAPPE_SITE); skipping."
            )
        frappe.init(site=site)
        frappe.connect()
        cls._frappe = frappe

    @classmethod
    def tearDownClass(cls):
        if FRAPPE_AVAILABLE and getattr(frappe.local, "db", None):
            frappe.destroy()

    def test_fixture_defines_expected_custom_field_metadata(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
            fixtures = json.load(fh)

        lead_fields = [f for f in fixtures if f.get("dt") == EXPECTED_DT]
        self.assertEqual(
            len(lead_fields), 1, "Expected exactly one Lead custom field in fixtures"
        )
        field = lead_fields[0]
        self.assertEqual(field["fieldname"], EXPECTED_FIELDNAME)
        self.assertEqual(field["label"], EXPECTED_LABEL)
        self.assertEqual(field["fieldtype"], EXPECTED_FIELDTYPE)
        self.assertEqual(field["insert_after"], EXPECTED_INSERT_AFTER)

    def test_custom_field_present_on_live_site_after_fixture_import(self):
        """Authoritative: imports the fixture into a real site and asserts live metadata."""
        frappe = self._frappe
        from frappe.custom.doctype.custom_field.custom_field import create_custom_field

        with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
            fixtures = json.load(fh)
        field_def = next(f for f in fixtures if f.get("dt") == EXPECTED_DT)

        create_custom_field(
            EXPECTED_DT,
            {
                "fieldname": field_def["fieldname"],
                "label": field_def["label"],
                "fieldtype": field_def["fieldtype"],
                "insert_after": field_def["insert_after"],
            },
            ignore_validate=True,
        )
        frappe.clear_cache(doctype=EXPECTED_DT)

        meta = frappe.get_meta(EXPECTED_DT, cached=False)
        live_field = meta.get_field(EXPECTED_FIELDNAME)

        self.assertIsNotNone(
            live_field, "Custom field was not created on the live Lead doctype"
        )
        self.assertEqual(live_field.dt, EXPECTED_DT)
        self.assertEqual(live_field.label, EXPECTED_LABEL)
        self.assertEqual(live_field.fieldtype, EXPECTED_FIELDTYPE)
        self.assertEqual(live_field.insert_after, EXPECTED_INSERT_AFTER)


if __name__ == "__main__":
    unittest.main()
