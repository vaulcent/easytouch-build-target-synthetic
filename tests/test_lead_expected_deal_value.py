"""Evidence for the "Lead Custom Field" requirement.

Goal: add a custom Currency field "Expected Deal Value" to Lead, placed
directly below "Annual Revenue" (insert_after="annual_revenue").

On this app's Lead custom fields, another pre-existing Currency field
("Potential Value", fieldname potential_value) was previously fixtured
with insert_after=annual_revenue as well. Per the deterministic
completion contract, two custom fields must never share the same
insert_after anchor -- doing so makes Frappe's rendered order
nondeterministic across `bench migrate` runs. So:

* "expected_deal_value" is anchored directly to insert_after="annual_revenue"
  (exactly the anchor requested by this change), making it deterministically
  the field immediately below Annual Revenue.
* "potential_value" is re-anchored to insert_after="expected_deal_value" (a
  distinct anchor), chaining it immediately below the new field instead of
  racing Expected Deal Value for the same annual_revenue anchor.

This module hosts two cases:

* TestLeadExpectedDealValueFixture - a quick structural smoke check of the
  fixture source in synthetic_build_target_app/fixtures/custom_field.json.
  This is NOT, by itself, evidence of real ERPNext behavior.

* TestLeadExpectedDealValueBehavior - the authoritative, Frappe-backed
  case. It is marked with the literal EASYTOUCH_ERP_BEHAVIOR_KINDS tuple
  below and proves, against a real disposable ERPNext v16 site, the exact
  DocType, label, fieldtype, and insert_after position of the custom field
  after fixture import (recreating both Lead custom fields in the same
  order `bench migrate` applies the fixtures file), plus that a Lead
  document can round-trip a value through it. It is skipped only when
  Frappe is unavailable in this local sandbox.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

try:
    import frappe  # type: ignore

    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "custom_field.json",
)


def _load_fixtures():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_lead_fixture(fieldname):
    fixtures = _load_fixtures()
    matches = [
        f
        for f in fixtures
        if f.get("doctype") == "Custom Field"
        and f.get("dt") == "Lead"
        and f.get("fieldname") == fieldname
    ]
    return matches


class TestLeadExpectedDealValueFixture(unittest.TestCase):
    def test_fixture_defines_expected_deal_value_on_lead(self):
        matches = _load_lead_fixture("expected_deal_value")
        self.assertEqual(
            len(matches),
            1,
            "Expected exactly one Expected Deal Value custom field fixture for Lead",
        )
        field = matches[0]
        self.assertEqual(field.get("label"), "Expected Deal Value")
        self.assertEqual(field.get("fieldtype"), "Currency")
        # Anchored directly to the requested anchor, so it deterministically
        # renders immediately below Annual Revenue.
        self.assertEqual(field.get("insert_after"), "annual_revenue")

    def test_fixture_potential_value_chained_after_expected_deal_value(self):
        matches = _load_lead_fixture("potential_value")
        self.assertEqual(len(matches), 1)
        # Re-anchored to a distinct anchor (not "annual_revenue") so it no
        # longer races Expected Deal Value for the same insert_after slot.
        self.assertEqual(matches[0].get("insert_after"), "expected_deal_value")

    def test_no_two_lead_custom_fields_share_an_insert_after_anchor(self):
        fixtures = _load_fixtures()
        lead_fields = [
            f
            for f in fixtures
            if f.get("doctype") == "Custom Field" and f.get("dt") == "Lead"
        ]
        anchors = [f.get("insert_after") for f in lead_fields]
        self.assertEqual(
            len(anchors),
            len(set(anchors)),
            "Two Lead custom fields must not share the same insert_after anchor",
        )


class TestLeadExpectedDealValueBehavior(unittest.TestCase):
    """EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

    Authoritative ERPNext-backed evidence. Run for real against a fresh
    disposable ERPNext v16 site in the post-finish validation lanes; only
    skipped here because Frappe is intentionally unavailable in this local
    sandbox.
    """

    _connected_here = False

    @classmethod
    def setUpClass(cls):
        if not FRAPPE_AVAILABLE:
            raise unittest.SkipTest("Frappe is unavailable in this local sandbox")
        # Reuse an already-active Frappe database context (e.g. when loaded
        # by `bench execute`); only initialize/connect from frappe.local.site
        # when no db context is already present. Never require a custom
        # site-name environment variable.
        if not getattr(frappe.local, "db", None):
            site = getattr(frappe.local, "site", None)
            if site:
                frappe.connect()
                cls._connected_here = True

    @classmethod
    def tearDownClass(cls):
        if FRAPPE_AVAILABLE and cls._connected_here and getattr(frappe.local, "db", None):
            frappe.destroy()

    def test_custom_field_present_and_positioned_on_lead(self):
        from frappe.custom.doctype.custom_field.custom_field import (
            create_custom_fields,
        )

        # Recreate both Lead custom fields in the same order `bench migrate`
        # applies the fixtures file (expected_deal_value, then
        # potential_value), so the resulting position is the same one a
        # real disposable site ends up with.
        expected_deal_value_fixture = _load_lead_fixture("expected_deal_value")[0]
        potential_value_fixture = _load_lead_fixture("potential_value")[0]

        create_custom_fields(
            {
                "Lead": [
                    {
                        "fieldname": expected_deal_value_fixture["fieldname"],
                        "label": expected_deal_value_fixture["label"],
                        "fieldtype": expected_deal_value_fixture["fieldtype"],
                        "insert_after": expected_deal_value_fixture["insert_after"],
                    }
                ]
            },
            ignore_validate=True,
            update=True,
        )
        create_custom_fields(
            {
                "Lead": [
                    {
                        "fieldname": potential_value_fixture["fieldname"],
                        "label": potential_value_fixture["label"],
                        "fieldtype": potential_value_fixture["fieldtype"],
                        "insert_after": potential_value_fixture["insert_after"],
                    }
                ]
            },
            ignore_validate=True,
            update=True,
        )
        frappe.clear_cache(doctype="Lead")

        meta = frappe.get_meta("Lead")
        field = meta.get_field("expected_deal_value")
        self.assertIsNotNone(field)
        self.assertEqual(field.label, "Expected Deal Value")
        self.assertEqual(field.fieldtype, "Currency")
        self.assertEqual(field.insert_after, "annual_revenue")

        annual_revenue_idx = next(
            i for i, df in enumerate(meta.fields) if df.fieldname == "annual_revenue"
        )
        expected_deal_value_idx = next(
            i for i, df in enumerate(meta.fields) if df.fieldname == "expected_deal_value"
        )
        potential_value_idx = next(
            i for i, df in enumerate(meta.fields) if df.fieldname == "potential_value"
        )

        # Expected Deal Value sits directly below Annual Revenue (the
        # requested anchor), and Potential Value is chained directly below
        # Expected Deal Value via a distinct anchor.
        self.assertEqual(expected_deal_value_idx, annual_revenue_idx + 1)
        self.assertEqual(potential_value_idx, expected_deal_value_idx + 1)
        self.assertGreater(expected_deal_value_idx, annual_revenue_idx)

        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Owner Review Expected Deal Value Test Lead",
                "expected_deal_value": 12345,
            }
        ).insert(ignore_permissions=True)
        try:
            lead.reload()
            self.assertEqual(float(lead.expected_deal_value), 12345.0)
        finally:
            frappe.delete_doc("Lead", lead.name, force=True, ignore_permissions=True)


if __name__ == "__main__":
    unittest.main()
