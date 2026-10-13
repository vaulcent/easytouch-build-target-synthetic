"""Tests for the Lead "Potential Value" Custom Field.

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('dashboard',)

The static fixture-shape checks below run unconditionally in the local
sandbox (no Frappe available). The authoritative class at the bottom of
this module imports Frappe and, when a real Frappe/ERPNext v16 database
context is available (either via an active `frappe.local.db` reused from
`bench execute`, or initialized from `frappe.local.site`), proves that:

  * the Custom Field fixture was imported with the exact DocType, label,
    fieldtype, and insert_after value declared in the fixture file, and
  * a real Lead document can be created with a Potential Value and the
    value round-trips through an independent re-fetch from the database.

When Frappe is unavailable locally, that class is skipped via
unittest.skipUnless; it must execute (not skip) inside the disposable
ERPNext v16 validation site used by the authoritative lanes.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("dashboard",)

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)

EXPECTED_DT = "Lead"
EXPECTED_FIELDNAME = "potential_value"
EXPECTED_LABEL = "Potential Value"
EXPECTED_FIELDTYPE = "Currency"
EXPECTED_INSERT_AFTER = "annual_revenue"
EXPECTED_NAME = "Lead-potential_value"

try:
    import frappe  # noqa: F401

    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False


class TestLeadPotentialValueCustomField(unittest.TestCase):
    """Static fixture-shape checks (always run locally, no Frappe)."""

    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _potential_value_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Custom Field"
            and entry.get("dt") == EXPECTED_DT
            and entry.get("fieldname") == EXPECTED_FIELDNAME
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_potential_value_field_exists_exactly_once(self):
        entries = self._potential_value_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Potential Value' Custom Field fixture for "
            "Lead (idempotent - no duplicates).",
        )

    def test_potential_value_field_definition(self):
        entry = self._potential_value_entries()[0]
        self.assertEqual(entry["dt"], EXPECTED_DT)
        self.assertEqual(entry["fieldname"], EXPECTED_FIELDNAME)
        self.assertEqual(entry["label"], EXPECTED_LABEL)
        self.assertEqual(entry["fieldtype"], EXPECTED_FIELDTYPE)
        self.assertEqual(entry["insert_after"], EXPECTED_INSERT_AFTER)
        self.assertEqual(entry["name"], EXPECTED_NAME)

    def test_existing_custom_fields_untouched(self):
        def count(dt, fieldname):
            return len(
                [
                    entry
                    for entry in self.fixtures
                    if entry.get("doctype") == "Custom Field"
                    and entry.get("dt") == dt
                    and entry.get("fieldname") == fieldname
                ]
            )

        self.assertEqual(count("Issue", "synthetic_reference"), 1)
        self.assertEqual(count("Lead", "referral_source"), 1)
        self.assertEqual(count("Task", "priority_tier"), 1)
        self.assertEqual(count("Opportunity", "release_pipeline_proof"), 1)

    def test_no_duplicate_dt_fieldname_pairs_overall(self):
        seen = set()
        for entry in self.fixtures:
            key = (entry.get("dt"), entry.get("fieldname"))
            self.assertNotIn(
                key, seen, f"Duplicate Custom Field fixture detected for {key}"
            )
            seen.add(key)


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is unavailable in this local sandbox; this class is the "
    "authoritative ERPNext v16 behavior evidence and must execute inside "
    "the disposable bench execute validation site.",
)
class TestLeadPotentialValueCustomFieldERP(unittest.TestCase):
    """Authoritative Frappe-backed evidence for the Lead Potential Value field."""

    @classmethod
    def setUpClass(cls):
        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()
        frappe.set_user("Administrator")
        cls._created_leads = []

    @classmethod
    def tearDownClass(cls):
        for lead_name in cls._created_leads:
            if frappe.db.exists("Lead", lead_name):
                frappe.delete_doc("Lead", lead_name, force=True)
        frappe.db.commit()

    def test_custom_field_metadata_matches_fixture_after_import(self):
        meta = frappe.get_meta("Lead")
        field = meta.get_field(EXPECTED_FIELDNAME)
        self.assertIsNotNone(
            field,
            "Lead doctype metadata does not expose the 'potential_value' "
            "field; the Custom Field fixture was not imported.",
        )
        self.assertEqual(field.label, EXPECTED_LABEL)
        self.assertEqual(field.fieldtype, EXPECTED_FIELDTYPE)
        self.assertEqual(field.insert_after, EXPECTED_INSERT_AFTER)
        self.assertTrue(
            frappe.db.exists("Custom Field", EXPECTED_NAME),
            "Expected Custom Field record 'Lead-potential_value' not found.",
        )

    def test_lead_can_be_created_with_potential_value_and_round_trips(self):
        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Easytouch Potential Value Behavior Test Lead",
                "potential_value": 125000,
            }
        )
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        self.__class__._created_leads.append(lead.name)

        refetched = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(refetched.potential_value), 125000.0)

        independent_value = frappe.db.get_value(
            "Lead", lead.name, "potential_value"
        )
        self.assertEqual(float(independent_value), 125000.0)


if __name__ == "__main__":
    unittest.main()
