"""Authoritative evidence for the Lead "Potential Deal Value" Custom Field.

Requirement: when creating a Lead, the user must have somewhere on the Lead
screen to record how much the lead could be worth as a customer.

This module contains:
  * Local, dependency-free structural checks against the fixture file that run
    in any sandbox (no Frappe required).
  * A Frappe-backed authoritative test class that imports Frappe, reuses the
    active `bench execute` database context (or initializes it from
    `frappe.local.site` when needed), imports the fixture, and proves the
    exact DocType, label, fieldtype, and insert_after value are live on the
    Lead doctype metadata after fixture import - then creates a real Lead,
    sets the field, and proves the value round-trips through the database.
    Every Lead created by this test is deleted after assertions.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('dashboard',)

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)

EXPECTED_NAME = "Lead-potential_value"
EXPECTED_DT = "Lead"
EXPECTED_FIELDNAME = "potential_value"
EXPECTED_FIELDTYPE = "Currency"
EXPECTED_LABEL = "Potential Deal Value"
EXPECTED_INSERT_AFTER = "annual_revenue"

try:
    import frappe  # noqa: F401

    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False


class TestLeadPotentialValueCustomFieldFixture(unittest.TestCase):
    """Sandbox-safe structural checks of the fixture definition itself."""

    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _entries(self):
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
        entries = self._entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Potential Deal Value' Custom Field fixture "
            "for Lead (idempotent - no duplicates).",
        )

    def test_potential_value_field_definition(self):
        entry = self._entries()[0]
        self.assertEqual(entry["name"], EXPECTED_NAME)
        self.assertEqual(entry["dt"], EXPECTED_DT)
        self.assertEqual(entry["fieldname"], EXPECTED_FIELDNAME)
        self.assertEqual(entry["fieldtype"], EXPECTED_FIELDTYPE)
        self.assertEqual(entry["label"], EXPECTED_LABEL)
        self.assertEqual(entry["insert_after"], EXPECTED_INSERT_AFTER)

    def test_existing_custom_fields_untouched(self):
        other_pairs = {
            ("Issue", "synthetic_reference"),
            ("Lead", "referral_source"),
            ("Task", "priority_tier"),
            ("Opportunity", "release_pipeline_proof"),
        }
        present_pairs = {
            (entry.get("dt"), entry.get("fieldname")) for entry in self.fixtures
        }
        for pair in other_pairs:
            self.assertIn(pair, present_pairs)

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
    "Frappe is not available in this local coding sandbox; this authoritative "
    "case must execute against a real disposable ERPNext v16 site via "
    "`bench execute` after finish.",
)
class TestLeadPotentialValueCustomFieldErpBehavior(unittest.TestCase):
    """Authoritative, Frappe-backed proof that the Custom Field is live and
    that the Lead screen can actually store the estimated customer value.
    """

    @classmethod
    def setUpClass(cls):
        import frappe

        if not getattr(frappe.local, "db", None):
            frappe.init(site=frappe.local.site)
            frappe.connect()
        cls.frappe = frappe
        cls._created_lead_names = []

    @classmethod
    def tearDownClass(cls):
        frappe = cls.frappe
        for lead_name in cls._created_lead_names:
            if frappe.db.exists("Lead", lead_name):
                frappe.delete_doc("Lead", lead_name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_custom_field_metadata_matches_fixture_after_import(self):
        frappe = self.frappe
        self.assertTrue(
            frappe.db.exists("Custom Field", EXPECTED_NAME),
            "Expected the Lead-potential_value Custom Field to exist on the "
            "site after fixture import.",
        )
        cf = frappe.get_doc("Custom Field", EXPECTED_NAME)
        self.assertEqual(cf.dt, EXPECTED_DT)
        self.assertEqual(cf.fieldname, EXPECTED_FIELDNAME)
        self.assertEqual(cf.fieldtype, EXPECTED_FIELDTYPE)
        self.assertEqual(cf.label, EXPECTED_LABEL)
        self.assertEqual(cf.insert_after, EXPECTED_INSERT_AFTER)

        meta = frappe.get_meta("Lead")
        meta_field = meta.get_field(EXPECTED_FIELDNAME)
        self.assertIsNotNone(
            meta_field,
            "Expected potential_value to be a resolvable field on the live "
            "Lead doctype metadata (i.e. visible on the Lead screen).",
        )
        self.assertEqual(meta_field.fieldtype, EXPECTED_FIELDTYPE)
        self.assertEqual(meta_field.label, EXPECTED_LABEL)
        self.assertEqual(meta_field.insert_after, EXPECTED_INSERT_AFTER)

    def test_lead_round_trips_potential_value(self):
        frappe = self.frappe
        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Easytouch Potential Value Evidence Lead",
                "company_name": "Easytouch Potential Value Evidence Co",
                "potential_value": 125000.50,
            }
        )
        lead.insert(ignore_permissions=True)
        self._created_lead_names.append(lead.name)
        frappe.db.commit()

        reloaded = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(reloaded.potential_value), 125000.50)

        independently_queried = frappe.db.get_value(
            "Lead", lead.name, "potential_value"
        )
        self.assertEqual(float(independently_queried), 125000.50)


if __name__ == "__main__":
    unittest.main()
