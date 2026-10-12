"""Authoritative ERPNext v16 behavior evidence for the "Potential Value"
Lead Custom Field.

Proves, against a real disposable ERPNext v16 site, that importing this
app's fixtures (the same idempotent ``fixtures/custom_field.json`` sync
that runs on every real ``bench migrate``) provisions a live "Custom
Field" record attached to DocType "Lead" with field name
"potential_value", label "Potential Value", fieldtype "Currency",
inserted immediately after the standard "annual_revenue" field -- and
that the field is then genuinely present on the live Lead DocType's meta
(i.e. it actually reaches the Lead screen), never via a mocked Frappe/
database stand-in.

Loaded by ``bench execute`` with an active Frappe database context: reuses
``frappe.local.db`` when already present, and only initializes from
``frappe.local.site`` when needed. Skips only when Frappe itself is
unavailable in this local coding sandbox.
"""

from __future__ import annotations

import importlib.util
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

FRAPPE_AVAILABLE = importlib.util.find_spec("frappe") is not None


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; this authoritative "
    "case must run inside a real disposable ERPNext v16 site via "
    "bench execute.",
)
class TestLeadPotentialValueCustomFieldBehavior(unittest.TestCase):
    CUSTOM_FIELD_NAME = "Lead-potential_value"

    @classmethod
    def setUpClass(cls):
        import frappe

        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        cls.frappe = frappe
        frappe.set_user("Administrator")

        # Re-run the real idempotent fixture sync this app registers for
        # "Custom Field" (see hooks.py's ``fixtures`` list) so the
        # on-disk fixtures/custom_field.json definition is genuinely
        # (re)applied to this live site, exactly as a real
        # ``bench migrate`` would.
        from frappe.utils.fixtures import sync_fixtures

        sync_fixtures(app="synthetic_build_target_app")
        frappe.db.commit()

    def test_potential_value_custom_field_provisioned_with_exact_definition(self):
        frappe = self.frappe

        self.assertTrue(
            frappe.db.exists("Custom Field", self.CUSTOM_FIELD_NAME),
            "fixture sync must create the Lead-potential_value Custom Field",
        )

        field = frappe.get_doc("Custom Field", self.CUSTOM_FIELD_NAME)
        self.assertEqual(field.dt, "Lead")
        self.assertEqual(field.fieldname, "potential_value")
        self.assertEqual(field.label, "Potential Value")
        self.assertEqual(field.fieldtype, "Currency")
        self.assertEqual(field.insert_after, "annual_revenue")

    def test_potential_value_field_reaches_the_live_lead_doctype_meta(self):
        frappe = self.frappe

        meta = frappe.get_meta("Lead", cached=False)
        df = meta.get_field("potential_value")
        self.assertIsNotNone(
            df, "the live Lead DocType meta must expose the new field"
        )
        self.assertEqual(df.label, "Potential Value")
        self.assertEqual(df.fieldtype, "Currency")
        self.assertEqual(df.insert_after, "annual_revenue")

    def test_re_running_fixture_sync_stays_idempotent(self):
        frappe = self.frappe

        before = frappe.db.count(
            "Custom Field", {"dt": "Lead", "fieldname": "potential_value"}
        )
        self.assertEqual(before, 1)

        from frappe.utils.fixtures import sync_fixtures

        sync_fixtures(app="synthetic_build_target_app")
        frappe.db.commit()

        after = frappe.db.count(
            "Custom Field", {"dt": "Lead", "fieldname": "potential_value"}
        )
        self.assertEqual(
            after,
            1,
            "re-running the fixture sync must not create a duplicate "
            "Lead-potential_value Custom Field",
        )


if __name__ == "__main__":
    unittest.main()
