"""Authoritative behavior test for: "Add an Estimated Value field to the Lead screen".

This module is the dedicated, compact, authoritative behavior-test module for the
requested change (adding a field to the Lead creation screen to capture the estimated
worth of a prospective customer). It intentionally avoids expanding any larger historical
mock/static suite.

The authoritative evidence for ERPNext behavior must come from a real, Frappe-backed
read against a fresh disposable ERPNext v16 site after the `Custom Field` fixture for
this app has been imported (e.g. via `bench --site <site> migrate` or
`bench --site <site> import-fixtures`). This test is skipped only when Frappe itself is
not importable in the local sandbox (Frappe is intentionally unavailable there); it must
never be a source-inspection-only, mocked, or placeholder check.
"""

import json
import os
import unittest

# Literal marker required by the completion contract so the authoritative run can
# identify and execute this module against a real ERPNext v16 site.
EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

try:
    import frappe  # type: ignore

    FRAPPE_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when Frappe is absent
    FRAPPE_AVAILABLE = False

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_PATH = os.path.join(
    APP_ROOT, "synthetic_build_target_app", "fixtures", "custom_field.json"
)


class TestLeadEstimatedValueCustomField(unittest.TestCase):
    """Proves the Lead -> Estimated Value Custom Field exists with the exact
    DocType, label, fieldtype, and insert_after value after fixture import."""

    def test_fixture_definition_is_well_formed(self):
        """Non-Frappe sanity check: the fixture that will be imported into the
        real site defines exactly the field we expect, with the right shape."""
        with open(FIXTURE_PATH, encoding="utf-8") as handle:
            records = json.load(handle)

        lead_fields = [r for r in records if r.get("dt") == "Lead"]
        self.assertEqual(
            len(lead_fields), 1, "Expected exactly one Lead custom field fixture entry"
        )
        field = lead_fields[0]
        self.assertEqual(field["fieldname"], "estimated_value")
        self.assertEqual(field["label"], "Estimated Value")
        self.assertEqual(field["fieldtype"], "Currency")
        self.assertEqual(field["insert_after"], "annual_revenue")

    @unittest.skipUnless(
        FRAPPE_AVAILABLE,
        "Frappe is unavailable in this local sandbox; authoritative evidence is "
        "gathered in a fresh disposable ERPNext v16 site in the real validation lane.",
    )
    def test_custom_field_exists_on_live_site_after_fixture_import(self):
        """Live Frappe read: after fixtures are imported on a real ERPNext v16
        site, the Custom Field must exist on the Lead DocType with the exact
        label, fieldtype, and insert_after position, and it must be usable on
        a newly created Lead document (proving it reaches the lead screen)."""
        custom_field_name = "Lead-estimated_value"

        self.assertTrue(
            frappe.db.exists("Custom Field", custom_field_name),
            "Custom Field 'Lead-estimated_value' was not found; run fixture "
            "import (e.g. `bench --site <site> migrate`) on a real ERPNext v16 site.",
        )

        doc = frappe.get_doc("Custom Field", custom_field_name)
        self.assertEqual(doc.dt, "Lead")
        self.assertEqual(doc.fieldname, "estimated_value")
        self.assertEqual(doc.label, "Estimated Value")
        self.assertEqual(doc.fieldtype, "Currency")
        self.assertEqual(doc.insert_after, "annual_revenue")

        # Prove the field actually reaches the Lead screen/doctype meta and is
        # writable, i.e. a real captured value on a created Lead.
        meta = frappe.get_meta("Lead")
        meta_field = meta.get_field("estimated_value")
        self.assertIsNotNone(meta_field)
        self.assertEqual(meta_field.fieldtype, "Currency")
        self.assertEqual(meta_field.label, "Estimated Value")
        self.assertEqual(meta_field.insert_after, "annual_revenue")

        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Estimated Value Behavior Test Lead",
                "estimated_value": 15000,
            }
        )
        lead.insert(ignore_permissions=True)
        try:
            saved_value = frappe.db.get_value(
                "Lead", lead.name, "estimated_value"
            )
            self.assertEqual(saved_value, 15000)
        finally:
            frappe.delete_doc("Lead", lead.name, force=True, ignore_permissions=True)


if __name__ == "__main__":
    unittest.main()
