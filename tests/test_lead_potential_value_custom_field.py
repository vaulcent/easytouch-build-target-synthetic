"""Authoritative ERPNext-backed evidence for the Lead "Potential Value" field.

Requirement: "When we create a lead, I want somewhere to enter how much we
think that customer could be worth."

This module is the dedicated, compact, Frappe-backed authority for that
change. It proves, against a live ERPNext v16 site (a real Frappe/MariaDB
connection, never a mocked Frappe or database layer), that after fixture
import the Lead doctype carries a Custom Field named "potential_value" with
the exact label and fieldtype requested. If Frappe is unavailable in this
local sandbox, the case skips (never silently mocks) and the two configured
validation lanes remain responsible for the authoritative post-finish run
on a disposable site.

Note on insert_after: a later requirement added another Lead Currency
custom field, "Expected Deal Value" (fieldname expected_deal_value), which
the completion contract for that change requires to be anchored directly
to insert_after="annual_revenue". To avoid two Lead custom fields racing
for the same insert_after anchor (nondeterministic final position on
migrate), Potential Value is chained to insert_after="expected_deal_value"
instead -- keeping it directly below Expected Deal Value, which itself
sits directly below Annual Revenue.
"""

import json
import os
import unittest

# Literal tuple required by the completion contract: the canonical set of
# ERP-behavior kinds this change may be marked under. This change is a
# Custom Field addition, so BEHAVIOR_KIND below must be a member of it.
EASYTOUCH_ERP_BEHAVIOR_KINDS = (
    "custom_field",
    "doc_event_hook",
    "dashboard_report",
    "workflow_approval",
)

BEHAVIOR_KIND = "custom_field"
assert BEHAVIOR_KIND in EASYTOUCH_ERP_BEHAVIOR_KINDS

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_PATH = os.path.join(
    REPO_ROOT,
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)

try:
    import frappe  # type: ignore
except Exception:  # pragma: no cover - environment-dependent
    frappe = None


class TestLeadPotentialValueCustomField(unittest.TestCase):
    """EASYTOUCH_ERP_BEHAVIOR_KINDS = custom_field"""

    @classmethod
    def setUpClass(cls):
        if frappe is None:
            raise unittest.SkipTest(
                "Frappe is unavailable in this local sandbox; the authoritative "
                "ERPNext v16 validation lanes run this case post-finish."
            )
        if getattr(frappe.local, "db", None) is None:
            site = os.environ.get("FRAPPE_SITE") or os.environ.get("SITE_NAME") or frappe.local.site
            try:
                frappe.init(site=site)
                frappe.connect()
            except Exception as exc:  # pragma: no cover - environment-dependent
                raise unittest.SkipTest(f"Could not connect to Frappe site: {exc}")
        frappe.set_user("Administrator")

    def test_fixture_defines_expected_lead_custom_field(self):
        """Sanity: the fixture on disk declares the exact field this
        behavior test will prove exists live on a Frappe-backed Lead meta.
        """
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            fixtures = json.load(handle)
        lead_fields = [
            f
            for f in fixtures
            if f.get("dt") == "Lead" and f.get("fieldname") == "potential_value"
        ]
        self.assertEqual(len(lead_fields), 1)
        field = lead_fields[0]
        self.assertEqual(field["fieldname"], "potential_value")
        self.assertEqual(field["label"], "Potential Value")
        self.assertEqual(field["fieldtype"], "Currency")
        self.assertEqual(field["insert_after"], "expected_deal_value")

    def test_lead_meta_has_potential_value_currency_field_live(self):
        """Live, Frappe-backed proof: after fixture import on a disposable
        ERPNext v16 site, Lead's meta carries the custom field with the
        exact doctype, label, and fieldtype.
        """
        frappe.reload_doc("core", "doctype", "custom_field", force=True)
        frappe.clear_cache(doctype="Lead")
        meta = frappe.get_meta("Lead")
        field = meta.get_field("potential_value")
        self.assertIsNotNone(
            field, "Lead meta is missing the potential_value custom field"
        )
        self.assertEqual(field.label, "Potential Value")
        self.assertEqual(field.fieldtype, "Currency")
        self.assertTrue(bool(frappe.db.get_value(
            "Custom Field", {"dt": "Lead", "fieldname": "potential_value"}, "name"
        )), "Custom Field row for Lead.potential_value not found in the database")

    def test_lead_can_be_created_with_potential_value(self):
        """Live, Frappe-backed proof: a user can actually enter the value on
        the Lead screen (create a Lead with potential_value set) and it
        persists, rather than only existing as metadata.
        """
        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Potential Value Behavior Test Lead",
                "potential_value": 125000,
            }
        )
        lead.insert(ignore_permissions=True)
        try:
            saved = frappe.get_doc("Lead", lead.name)
            self.assertEqual(float(saved.potential_value), 125000.0)
        finally:
            frappe.delete_doc("Lead", lead.name, force=True, ignore_permissions=True)
            frappe.db.commit()


if __name__ == "__main__":
    unittest.main()
