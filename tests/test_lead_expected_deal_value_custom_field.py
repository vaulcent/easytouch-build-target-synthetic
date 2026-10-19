"""Authoritative ERP-behavior evidence for the Lead "Expected Deal Value" Custom Field.

This module proves, against a real disposable ERPNext v16 site, that:
  * exactly one Currency Custom Field named "Expected Deal Value" exists on Lead
    with fieldname `expected_deal_value`,
  * its `insert_after` is `annual_revenue` directly (not via another custom field
    anchored on top of `annual_revenue`),
  * the rendered meta field order places it immediately after `annual_revenue`,
  * a real Lead document is inserted, reloaded from the database, and the
    stored value persists across that insert + reload round trip.

Frappe is intentionally unavailable in the local coding sandbox, so these cases
skip locally via skipUnless and are designed to execute for real under
`bench execute` against a disposable ERPNext v16 validation site.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe  # type: ignore
    FRAPPE_AVAILABLE = True
except Exception:  # pragma: no cover - expected in the local coding sandbox
    frappe = None
    FRAPPE_AVAILABLE = False


FIELDNAME = "expected_deal_value"
LABEL = "Expected Deal Value"
FIELDTYPE = "Currency"
INSERT_AFTER = "annual_revenue"
CUSTOM_FIELD_NAME = "Lead-expected_deal_value"
EXPECTED_VALUE = 125000.50


def _ensure_frappe_context():
    """Reuse the active bench execute DB context, or init from frappe.local.site."""
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is unavailable in this local sandbox")
class TestLeadExpectedDealValueCustomField(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _ensure_frappe_context()
        frappe.set_user("Administrator")
        cls._created_custom_field = False

        if not frappe.db.exists("Custom Field", CUSTOM_FIELD_NAME):
            fixtures_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "synthetic_build_target_app",
                "fixtures",
                "custom_field.json",
            )
            with open(fixtures_path, "r", encoding="utf-8") as handle:
                fixture_records = json.load(handle)
            record = next(
                r for r in fixture_records if r.get("name") == CUSTOM_FIELD_NAME
            )
            doc = frappe.get_doc(record)
            doc.insert(ignore_permissions=True)
            cls._created_custom_field = True

        frappe.clear_cache(doctype="Lead")

    @classmethod
    def tearDownClass(cls):
        if cls._created_custom_field and frappe.db.exists("Custom Field", CUSTOM_FIELD_NAME):
            frappe.delete_doc("Custom Field", CUSTOM_FIELD_NAME, force=True, ignore_permissions=True)
            frappe.clear_cache(doctype="Lead")
        frappe.db.commit()

    def test_exactly_one_custom_field_with_exact_metadata(self):
        matches = frappe.get_all(
            "Custom Field",
            filters={"dt": "Lead", "fieldname": FIELDNAME},
            fields=["name", "label", "fieldtype", "insert_after"],
        )
        self.assertEqual(
            len(matches), 1,
            "Expected exactly one Custom Field named %r on Lead" % FIELDNAME,
        )
        record = matches[0]
        self.assertEqual(record["label"], LABEL)
        self.assertEqual(record["fieldtype"], FIELDTYPE)
        self.assertEqual(record["insert_after"], INSERT_AFTER)

        # No other custom field is chained on top of the same anchor, which
        # would make our field's position non-deterministic.
        other_anchors = frappe.get_all(
            "Custom Field",
            filters={"dt": "Lead", "insert_after": INSERT_AFTER, "fieldname": ["!=", FIELDNAME]},
        )
        self.assertEqual(
            len(other_anchors), 0,
            "Another custom field shares the same insert_after anchor",
        )

    def test_rendered_meta_order_is_directly_after_anchor(self):
        meta = frappe.get_meta("Lead")
        fieldnames = [df.fieldname for df in meta.fields]

        self.assertIn(INSERT_AFTER, fieldnames)
        self.assertIn(FIELDNAME, fieldnames)

        anchor_index = fieldnames.index(INSERT_AFTER)
        target_index = fieldnames.index(FIELDNAME)
        self.assertEqual(
            target_index, anchor_index + 1,
            "Expected Deal Value must render immediately after Annual Revenue",
        )

        target_df = meta.get_field(FIELDNAME)
        self.assertEqual(target_df.fieldtype, FIELDTYPE)
        self.assertEqual(target_df.label, LABEL)
        self.assertEqual(target_df.insert_after, INSERT_AFTER)

    def test_value_persists_on_a_real_lead_document(self):
        lead = frappe.get_doc({
            "doctype": "Lead",
            "lead_name": "Easytouch QA Expected Deal Value",
            "email_id": "easytouch.qa.expected.deal.value@example.test",
            "expected_deal_value": EXPECTED_VALUE,
        })
        # Insert a real Lead document on the live site.
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        lead_name = lead.name

        try:
            # Reload the same in-memory document straight from the database.
            lead.reload()
            self.assertEqual(float(lead.expected_deal_value), EXPECTED_VALUE)

            # Also fetch a brand-new document instance to prove the value was
            # durably persisted, not merely retained in memory.
            reloaded = frappe.get_doc("Lead", lead_name)
            reloaded.reload()
            self.assertEqual(float(reloaded.expected_deal_value), EXPECTED_VALUE)
        finally:
            frappe.delete_doc("Lead", lead_name, force=True, ignore_permissions=True)
            frappe.db.commit()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
