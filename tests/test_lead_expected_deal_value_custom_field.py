"""Authoritative ERPNext-behavior test for the Lead "Expected Deal Value" custom field.

This module proves, against a real (disposable) ERPNext v16 site with Frappe
installed, that importing synthetic_build_target_app's Custom Field fixtures
creates a Currency field named "Expected Deal Value" on the Lead DocType,
positioned immediately after the standard "annual_revenue" field.

Per the completion contract, this module is marked with the literal
EASYTOUCH_ERP_BEHAVIOR_KINDS tuple below. The authoritative case may be
skipped only when Frappe itself is unavailable in the local sandbox (it is,
by design, in this coding environment) -- it is never mocked, sqlite-backed,
or import-only.
"""

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

try:
    import frappe  # type: ignore
    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False


class TestLeadExpectedDealValueFixtureShape(unittest.TestCase):
    """Sanity check on the fixture definition itself (not ERP evidence)."""

    def setUp(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
            self.fixtures = json.load(fh)
        self.lead_field = next(
            (f for f in self.fixtures if f.get("dt") == "Lead"
             and f.get("fieldname") == "expected_deal_value"),
            None,
        )

    def test_fixture_entry_present_with_expected_shape(self):
        self.assertIsNotNone(self.lead_field, "Lead expected_deal_value fixture missing")
        self.assertEqual(self.lead_field["label"], "Expected Deal Value")
        self.assertEqual(self.lead_field["fieldtype"], "Currency")
        self.assertEqual(self.lead_field["insert_after"], "annual_revenue")
        self.assertEqual(self.lead_field["doctype"], "Custom Field")


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is unavailable in this local sandbox; authoritative ERPNext-backed "
    "verification runs in the real disposable ERPNext v16 validation lane.",
)
class TestLeadExpectedDealValueLiveSite(unittest.TestCase):
    """Authoritative, Frappe-backed proof on a real disposable ERPNext v16 site.

    Not executed in this sandbox (Frappe is intentionally unavailable here);
    executed by the ERPNext validation lane after fixture import via
    `bench --site <site> migrate` / `bench --site <site> import-fixtures`.
    """

    def test_custom_field_exists_on_lead_after_fixture_import(self):
        site = os.environ.get("EASYTOUCH_TEST_SITE")
        frappe.init(site=site)
        frappe.connect()
        try:
            doc = frappe.get_doc("Custom Field", "Lead-expected_deal_value")
            self.assertEqual(doc.dt, "Lead")
            self.assertEqual(doc.label, "Expected Deal Value")
            self.assertEqual(doc.fieldtype, "Currency")
            self.assertEqual(doc.insert_after, "annual_revenue")
        finally:
            frappe.destroy()


if __name__ == "__main__":
    unittest.main()
