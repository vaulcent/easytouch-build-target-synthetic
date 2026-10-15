"""Authoritative ERPNext-backed evidence for the Lead "Expected Deal Value" custom field.

This module is intentionally small and dedicated to the single requested change:
add a Currency custom field called "Expected Deal Value" to the Lead doctype,
positioned immediately after the standard "Annual Revenue" field (fieldname
``annual_revenue``).

Per the completion contract, this module is marked with the literal
EASYTOUCH_ERP_BEHAVIOR_KINDS tuple below. These cases may only be skipped when
Frappe itself is unavailable in the local sandbox (which is expected here --
Frappe/ERPNext is intentionally not installed in this coding sandbox). The
authoritative run against a real, disposable ERPNext v16 site is performed by
the two configured validation lanes after this change reaches owner review.
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
    frappe = None
    FRAPPE_AVAILABLE = False


def _load_lead_field_definition():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        entries = json.load(handle)
    for entry in entries:
        if entry.get("dt") == "Lead" and entry.get("fieldname") == "expected_deal_value":
            return entry
    return None


class LeadExpectedDealValueFixtureShapeTests(unittest.TestCase):
    """Sandbox-safe structural check of the fixture that feeds the ERPNext import.

    This is a prerequisite sanity check, not the authoritative ERP-behavior
    evidence itself -- the authoritative, Frappe-backed proof lives in
    LeadExpectedDealValueFrappeBehaviorTests below and in the two real
    ERPNext v16 validation lanes that run after finish.
    """

    def test_fixture_declares_expected_currency_field_after_annual_revenue(self):
        entry = _load_lead_field_definition()
        self.assertIsNotNone(entry, "Lead custom field fixture entry not found")
        self.assertEqual(entry["doctype"], "Custom Field")
        self.assertEqual(entry["dt"], "Lead")
        self.assertEqual(entry["label"], "Expected Deal Value")
        self.assertEqual(entry["fieldtype"], "Currency")
        self.assertEqual(entry["insert_after"], "annual_revenue")


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is unavailable in this local sandbox; authoritative ERPNext v16 "
    "validation lanes run this behavior case against a real disposable site.",
)
class LeadExpectedDealValueFrappeBehaviorTests(unittest.TestCase):
    """Authoritative ERPNext v16 evidence (EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)).

    Imports the custom field fixture against a live, connected Frappe site and
    asserts the resulting Lead meta exposes the exact doctype, label,
    fieldtype, and insert_after position required by the acceptance
    criteria. The import is idempotent: running it twice must not create a
    duplicate field or raise.
    """

    @classmethod
    def setUpClass(cls):
        site = os.environ.get("FRAPPE_SITE") or os.environ.get("SITE")
        if not site:
            raise unittest.SkipTest(
                "No FRAPPE_SITE/SITE configured for this sandbox; the "
                "authoritative ERPNext v16 validation lanes supply a real "
                "disposable site after finish."
            )
        frappe.init(site=site)
        frappe.connect()
        cls._site = site

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_site", None):
            frappe.destroy()

    def _import_fixture_entry_idempotently(self, entry):
        existing = frappe.db.exists("Custom Field", entry["name"])
        if existing:
            doc = frappe.get_doc("Custom Field", entry["name"])
            doc.label = entry["label"]
            doc.fieldtype = entry["fieldtype"]
            doc.insert_after = entry["insert_after"]
            doc.save(ignore_permissions=True)
        else:
            doc = frappe.get_doc(entry)
            doc.insert(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache(doctype="Lead")

    def test_expected_deal_value_field_present_with_exact_shape_after_import(self):
        entry = _load_lead_field_definition()
        self.assertIsNotNone(entry)

        # Import once, then again, to prove idempotency of the fixture import.
        self._import_fixture_entry_idempotently(entry)
        self._import_fixture_entry_idempotently(entry)

        meta = frappe.get_meta("Lead")
        field = meta.get_field("expected_deal_value")
        self.assertIsNotNone(
            field, "expected_deal_value field missing from Lead meta after import"
        )
        self.assertEqual(field.fieldtype, "Currency")
        self.assertEqual(field.label, "Expected Deal Value")

        fieldnames = [df.fieldname for df in meta.fields]
        self.assertIn("annual_revenue", fieldnames)
        self.assertIn("expected_deal_value", fieldnames)
        self.assertEqual(
            fieldnames.index("expected_deal_value"),
            fieldnames.index("annual_revenue") + 1,
            "Expected Deal Value must immediately follow Annual Revenue in Lead meta",
        )

        only_one = frappe.db.count(
            "Custom Field", {"dt": "Lead", "fieldname": "expected_deal_value"}
        )
        self.assertEqual(only_one, 1, "Fixture import must be idempotent, not duplicate")


if __name__ == "__main__":
    unittest.main()
