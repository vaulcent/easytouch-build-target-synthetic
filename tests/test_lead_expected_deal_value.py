"""Evidence for the "Lead Custom Field" requirement.

Goal: add a custom Currency field "Expected Deal Value" to Lead, placed
below "Annual Revenue".

On this app's Lead custom fields, another pre-existing Currency field
("Potential Value", fieldname potential_value) is already fixtured with
insert_after=annual_revenue, i.e. it already occupies the slot
immediately below Annual Revenue. To avoid two custom fields both racing
for the exact same insert_after target (which produces a nondeterministic
final position when both are imported via `bench migrate`, as happened in
the previously rejected patch), the Expected Deal Value field explicitly
declares insert_after="potential_value". That keeps it correctly and
deterministically positioned below Annual Revenue (immediately below the
other revenue-related custom field that itself sits directly under Annual
Revenue), rather than silently losing a position race during migrate.

This module hosts two cases:

* TestLeadExpectedDealValueFixture - a quick structural smoke check of the
  fixture source in synthetic_build_target_app/fixtures/custom_field.json.
  This is NOT, by itself, evidence of real ERPNext behavior.

* TestLeadExpectedDealValueBehavior - the authoritative, Frappe-backed
  case. It is marked with EASYTOUCH_ERP_BEHAVIOR_KINDS below and proves,
  against a real disposable ERPNext v16 site, the exact DocType, label,
  fieldtype, and insert_after position of the custom field after fixture
  import (mirroring the real migrate order of both Lead custom fields),
  plus that a Lead document can round-trip a value through it. It is
  skipped only when Frappe is unavailable in this local sandbox.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("CUSTOM_FIELD",)

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
        # Explicitly anchored below the other pre-existing Lead currency
        # field that itself sits directly under Annual Revenue, so the
        # final position below Annual Revenue is deterministic on a real
        # site regardless of fixture import order.
        self.assertEqual(field.get("insert_after"), "potential_value")

    def test_fixture_potential_value_still_anchored_to_annual_revenue(self):
        matches = _load_lead_fixture("potential_value")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].get("insert_after"), "annual_revenue")


class TestLeadExpectedDealValueBehavior(unittest.TestCase):
    """EASYTOUCH_ERP_BEHAVIOR_KINDS = ("CUSTOM_FIELD",)

    Authoritative ERPNext-backed evidence. Run for real against a fresh
    disposable ERPNext v16 site in the post-finish validation lanes; only
    skipped here because Frappe is intentionally unavailable in this local
    sandbox.
    """

    @classmethod
    def setUpClass(cls):
        if not FRAPPE_AVAILABLE:
            raise unittest.SkipTest("Frappe is unavailable in this local sandbox")

    def test_custom_field_present_and_positioned_on_lead(self):
        from frappe.custom.doctype.custom_field.custom_field import (
            create_custom_fields,
        )

        # Recreate both Lead custom fields in the same order `bench migrate`
        # applies the fixtures file (potential_value, then
        # expected_deal_value), so the resulting position is the same one
        # a real disposable site ends up with.
        potential_value_fixture = _load_lead_fixture("potential_value")[0]
        expected_deal_value_fixture = _load_lead_fixture("expected_deal_value")[0]

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
        frappe.clear_cache(doctype="Lead")

        meta = frappe.get_meta("Lead")
        field = meta.get_field("expected_deal_value")
        self.assertIsNotNone(field)
        self.assertEqual(field.label, "Expected Deal Value")
        self.assertEqual(field.fieldtype, "Currency")
        self.assertEqual(field.insert_after, "potential_value")

        annual_revenue_idx = next(
            i for i, df in enumerate(meta.fields) if df.fieldname == "annual_revenue"
        )
        potential_value_idx = next(
            i for i, df in enumerate(meta.fields) if df.fieldname == "potential_value"
        )
        expected_deal_value_idx = next(
            i for i, df in enumerate(meta.fields) if df.fieldname == "expected_deal_value"
        )

        # Expected Deal Value sits directly below Potential Value, which
        # itself sits directly below Annual Revenue -- so Expected Deal
        # Value is deterministically below Annual Revenue.
        self.assertEqual(potential_value_idx, annual_revenue_idx + 1)
        self.assertEqual(expected_deal_value_idx, potential_value_idx + 1)
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
            self.assertEqual(lead.expected_deal_value, 12345)
        finally:
            frappe.delete_doc("Lead", lead.name, force=True, ignore_permissions=True)


if __name__ == "__main__":
    unittest.main()
