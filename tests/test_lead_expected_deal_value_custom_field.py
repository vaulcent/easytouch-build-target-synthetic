"""Authoritative ERPNext-behavior test for the Lead "Expected Deal Value" custom field.

Requirement: add a custom Currency field called "Expected Deal Value" to the Lead
DocType, placed immediately below "Annual Revenue" (insert_after="annual_revenue").

This module is the single dedicated behavior-test module for this change. It is
marked with EASYTOUCH_ERP_BEHAVIOR_KINDS so the authoritative post-finish run (a
fresh disposable ERPNext v16 site) can identify and execute it against a real,
unmocked Frappe/ERPNext site. In this local sandbox, Frappe is intentionally
unavailable, so the live-site case skips here and only proves fixture shape via
plain-JSON inspection (not treated as ERP behavior evidence by itself).

Live-site execution contract: when this module is run inside the disposable
ERPNext v16 site (e.g. via ``bench --site <site> run-tests --app
synthetic_build_target_app --module tests.test_lead_expected_deal_value_custom_field``,
or any runner that has already called ``frappe.init``/``frappe.connect`` for that
site before Python imports this module), the live behavior test subclasses
``frappe.tests.utils.FrappeTestCase`` and executes for real -- it must not be
skipped there. It only skips when the ``frappe`` package itself cannot be
imported at all, which is the case in this local, Frappe-free sandbox.
"""

import json
import os
import unittest

# Literal contract marker: declares which ERP-behavior categories this module
# authoritatively covers when run against a live ERPNext v16 site.
EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

APP_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
)
FIXTURE_PATH = os.path.join(APP_ROOT, "fixtures", "custom_field.json")

try:
    import frappe  # type: ignore
    from frappe.tests.utils import FrappeTestCase  # type: ignore
    FRAPPE_AVAILABLE = True
except Exception:
    frappe = None
    FrappeTestCase = None
    FRAPPE_AVAILABLE = False


class LeadExpectedDealValueFixtureShapeTest(unittest.TestCase):
    """Sanity-checks the fixture file this change ships (not ERP evidence alone)."""

    def setUp(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
            self.fixtures = json.load(fh)
        self.lead_field = next(
            (f for f in self.fixtures if f.get("dt") == "Lead"
             and f.get("fieldname") == "expected_deal_value"),
            None,
        )

    def test_lead_custom_field_present_in_fixture(self):
        self.assertIsNotNone(
            self.lead_field,
            "Expected a Custom Field fixture entry for Lead.expected_deal_value",
        )

    def test_lead_custom_field_shape(self):
        self.assertEqual(self.lead_field["doctype"], "Custom Field")
        self.assertEqual(self.lead_field["dt"], "Lead")
        self.assertEqual(self.lead_field["label"], "Expected Deal Value")
        self.assertEqual(self.lead_field["fieldtype"], "Currency")
        self.assertEqual(self.lead_field["insert_after"], "annual_revenue")
        self.assertEqual(self.lead_field["name"], "Lead-expected_deal_value")

    def test_existing_issue_fixture_untouched(self):
        issue_field = next(
            (f for f in self.fixtures if f.get("dt") == "Issue"
             and f.get("fieldname") == "synthetic_reference"),
            None,
        )
        self.assertIsNotNone(issue_field)
        self.assertEqual(issue_field["fieldtype"], "Data")


if FRAPPE_AVAILABLE:

    class LeadExpectedDealValueLiveSiteBehaviorTest(FrappeTestCase):
        """Live Frappe-backed proof: real DocType, label, fieldtype, insert_after.

        Subclasses ``FrappeTestCase`` so it runs inside whatever disposable
        ERPNext v16 site the test runner has already initialized/connected
        (the standard ``bench run-tests`` contract) -- it does not require any
        bespoke environment variable to opt in, so it cannot silently skip
        inside a real site merely because an ad-hoc env var was not set.
        """

        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            from frappe.modules.import_file import import_file_by_path
            import_file_by_path(FIXTURE_PATH, data_import=True, force=True)
            frappe.db.commit()

        def test_custom_field_imported_on_lead_with_exact_metadata(self):
            self.assertTrue(frappe.db.exists("Custom Field", "Lead-expected_deal_value"))
            cf = frappe.get_doc("Custom Field", "Lead-expected_deal_value")
            self.assertEqual(cf.dt, "Lead")
            self.assertEqual(cf.label, "Expected Deal Value")
            self.assertEqual(cf.fieldtype, "Currency")
            self.assertEqual(cf.insert_after, "annual_revenue")

            meta = frappe.get_meta("Lead")
            df = meta.get_field("expected_deal_value")
            self.assertIsNotNone(df, "expected_deal_value must appear on live Lead meta")
            self.assertEqual(df.fieldtype, "Currency")
            self.assertEqual(df.label, "Expected Deal Value")
            self.assertEqual(df.insert_after, "annual_revenue")

else:

    class LeadExpectedDealValueLiveSiteBehaviorTest(unittest.TestCase):
        """Placeholder shown only when `frappe` cannot be imported at all.

        This is the only condition under which the live-site behavior case is
        permitted to skip: this local sandbox has no Frappe installed. Inside
        the authoritative disposable ERPNext v16 site, `frappe` is always
        importable, so the real `FrappeTestCase` subclass above is used there
        and actually executes instead of skipping.
        """

        @unittest.skip(
            "Frappe is not installed in this local sandbox; the authoritative "
            "live-site case runs against the disposable ERPNext v16 site."
        )
        def test_skipped_because_frappe_unavailable_locally(self):
            pass


if __name__ == "__main__":
    unittest.main()
