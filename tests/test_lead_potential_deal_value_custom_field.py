"""Authoritative behavior test for the Lead "Potential Deal Value" Custom Field.

Requirement: When creating a Lead, the user wants a place to enter how much
they think that customer could be worth. This is implemented as a single
Custom Field on the standard ERPNext Lead DocType.

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)
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

EXPECTED_CUSTOM_FIELD_NAME = "Lead-potential_deal_value"
EXPECTED_DT = "Lead"
EXPECTED_FIELDNAME = "potential_deal_value"
EXPECTED_LABEL = "Potential Deal Value"
EXPECTED_FIELDTYPE = "Currency"
EXPECTED_INSERT_AFTER = "annual_revenue"

# Common env var names used by disposable-site test harnesses to point at the
# already-provisioned ERPNext v16 site. frappe.local.site (set automatically
# when tests are launched through bench's own test runner) is checked first,
# since that is the normal way an authoritative disposable-site run provides
# site context without any env var at all.
_SITE_ENV_VARS = ("FRAPPE_SITE", "SITE", "SITE_NAME", "BENCH_SITE")


def _resolve_site():
    """Resolve the disposable ERPNext site to connect to, if any.

    Returns None only when no site context can be determined at all, which
    should not happen on a real disposable ERPNext v16 site where this
    app's fixtures have been migrated in.
    """
    if not FRAPPE_AVAILABLE:
        return None

    existing_site = getattr(getattr(frappe, "local", None), "site", None)
    if existing_site:
        return existing_site

    for var in _SITE_ENV_VARS:
        value = os.environ.get(var)
        if value:
            return value

    return None


class TestLeadPotentialDealValueCustomField(unittest.TestCase):
    """EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)"""

    def _load_fixture_record(self):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
            records = json.load(fh)
        for record in records:
            if record.get("dt") == EXPECTED_DT and record.get("fieldname") == EXPECTED_FIELDNAME:
                return record
        self.fail("Lead potential_deal_value Custom Field fixture record not found")

    def test_fixture_defines_expected_custom_field_shape(self):
        record = self._load_fixture_record()
        self.assertEqual(record["name"], EXPECTED_CUSTOM_FIELD_NAME)
        self.assertEqual(record["dt"], EXPECTED_DT)
        self.assertEqual(record["fieldname"], EXPECTED_FIELDNAME)
        self.assertEqual(record["label"], EXPECTED_LABEL)
        self.assertEqual(record["fieldtype"], EXPECTED_FIELDTYPE)
        self.assertEqual(record["insert_after"], EXPECTED_INSERT_AFTER)

    @unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is unavailable in this local sandbox")
    def test_custom_field_exists_on_lead_after_fixture_import_in_frappe(self):
        """Authoritative ERPNext v16 check: run against a real, disposable site.

        This case is intentionally not mocked. It only skips when Frappe
        itself is unavailable (checked above). When Frappe is available it
        resolves the already-provisioned disposable site either from
        frappe.local.site (set by the bench test runner) or from one of the
        common site env vars, then connects and asserts against real
        metadata rather than source text.
        """
        site = _resolve_site()
        self.assertIsNotNone(
            site,
            "Frappe is available but no disposable ERPNext site context could be "
            "resolved (checked frappe.local.site and FRAPPE_SITE/SITE/SITE_NAME/"
            "BENCH_SITE env vars)",
        )

        already_connected = bool(getattr(frappe.local, "db", None))
        if not already_connected:
            frappe.init(site=site)
            frappe.connect()

        try:
            self.assertTrue(
                frappe.db.exists("Custom Field", EXPECTED_CUSTOM_FIELD_NAME),
                f"Expected Custom Field {EXPECTED_CUSTOM_FIELD_NAME} to exist after fixture import",
            )

            custom_field_doc = frappe.get_doc("Custom Field", EXPECTED_CUSTOM_FIELD_NAME)
            self.assertEqual(custom_field_doc.dt, EXPECTED_DT)
            self.assertEqual(custom_field_doc.fieldname, EXPECTED_FIELDNAME)
            self.assertEqual(custom_field_doc.label, EXPECTED_LABEL)
            self.assertEqual(custom_field_doc.fieldtype, EXPECTED_FIELDTYPE)
            self.assertEqual(custom_field_doc.insert_after, EXPECTED_INSERT_AFTER)

            lead_meta = frappe.get_meta("Lead")
            self.assertTrue(
                lead_meta.has_field(EXPECTED_FIELDNAME),
                "Lead meta should expose potential_deal_value after fixture import",
            )
            lead_field = lead_meta.get_field(EXPECTED_FIELDNAME)
            self.assertEqual(lead_field.fieldtype, EXPECTED_FIELDTYPE)
            self.assertEqual(lead_field.label, EXPECTED_LABEL)

            # Prove the field is also usable end-to-end: create a real Lead,
            # set the value, save, reload, and confirm it persists.
            lead = frappe.get_doc(
                {
                    "doctype": "Lead",
                    "lead_name": "Easytouch Behavior Test Lead",
                    "potential_deal_value": 12345.67,
                }
            )
            lead.insert(ignore_permissions=True)
            try:
                reloaded = frappe.get_doc("Lead", lead.name)
                self.assertEqual(float(reloaded.potential_deal_value), 12345.67)
            finally:
                frappe.delete_doc("Lead", lead.name, ignore_permissions=True, force=True)
        finally:
            if not already_connected:
                frappe.destroy()


if __name__ == "__main__":
    unittest.main()
