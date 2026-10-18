"""Authoritative behavior test for the Lead "Expected Deal Value" Custom Field.

This module is loaded both:
  1. Locally via `python3 -m unittest discover -s tests -v`, where Frappe is
     intentionally unavailable, so the entire module is skipped at import
     time via unittest.SkipTest (not silently swallowed with ImportError).
  2. Authoritatively via `bench execute` against a disposable ERPNext v16
     validation site, where Frappe IS available, `import frappe` succeeds,
     and the real database-backed assertions below must execute.
"""

import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe
except ImportError as exc:  # pragma: no cover - exercised only in this local sandbox
    raise unittest.SkipTest(
        "Frappe is unavailable in this local sandbox; this module runs for real "
        "against the disposable ERPNext v16 validation site via bench execute."
    ) from exc


FIELDNAME = "expected_deal_value"
ANCHOR_FIELDNAME = "annual_revenue"
DOCTYPE = "Lead"
LABEL = "Expected Deal Value"
FIELDTYPE = "Currency"
TEST_VALUE = 125000.50


def _ensure_db_context():
    """Reuse an already-active frappe.local.db, only initializing from
    frappe.local.site when no active database connection exists."""
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


def _ensure_custom_field():
    """Ensure exactly one Currency Custom Field named Lead-expected_deal_value
    exists with insert_after=annual_revenue, matching the shipped fixture."""
    cf_name = f"{DOCTYPE}-{FIELDNAME}"
    if frappe.db.exists("Custom Field", cf_name):
        cf = frappe.get_doc("Custom Field", cf_name)
        changed = False
        if cf.fieldtype != FIELDTYPE:
            cf.fieldtype = FIELDTYPE
            changed = True
        if cf.label != LABEL:
            cf.label = LABEL
            changed = True
        if cf.insert_after != ANCHOR_FIELDNAME:
            cf.insert_after = ANCHOR_FIELDNAME
            changed = True
        if changed:
            cf.save(ignore_permissions=True)
    else:
        cf = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "name": cf_name,
                "dt": DOCTYPE,
                "fieldname": FIELDNAME,
                "fieldtype": FIELDTYPE,
                "label": LABEL,
                "insert_after": ANCHOR_FIELDNAME,
            }
        )
        cf.insert(ignore_permissions=True)
    frappe.clear_cache(doctype=DOCTYPE)
    frappe.db.commit()
    return cf_name


class TestLeadExpectedDealValueCustomField(unittest.TestCase):

    created_lead_name = None
    created_custom_field_name = None

    @classmethod
    def setUpClass(cls):
        _ensure_db_context()
        cls.created_custom_field_name = _ensure_custom_field()

    @classmethod
    def tearDownClass(cls):
        if cls.created_lead_name and frappe.db.exists("Lead", cls.created_lead_name):
            frappe.delete_doc(
                "Lead", cls.created_lead_name, force=True, ignore_permissions=True
            )
            frappe.db.commit()

    def test_exactly_one_currency_field_with_correct_metadata(self):
        matches = frappe.get_all(
            "Custom Field",
            filters={"dt": DOCTYPE, "fieldname": FIELDNAME},
            fields=["name", "fieldtype", "label", "insert_after"],
        )
        self.assertEqual(
            len(matches),
            1,
            "Expected exactly one Custom Field for Lead.expected_deal_value",
        )
        match = matches[0]
        self.assertEqual(match["fieldtype"], FIELDTYPE)
        self.assertEqual(match["label"], LABEL)
        self.assertEqual(match["insert_after"], ANCHOR_FIELDNAME)

    def test_no_other_field_shares_the_anchor(self):
        sharing_anchor = frappe.get_all(
            "Custom Field",
            filters={"dt": DOCTYPE, "insert_after": ANCHOR_FIELDNAME},
            fields=["fieldname"],
        )
        fieldnames = {row["fieldname"] for row in sharing_anchor}
        self.assertEqual(
            fieldnames,
            {FIELDNAME},
            "Only expected_deal_value may be anchored directly after annual_revenue",
        )

    def test_rendered_order_immediately_after_anchor(self):
        meta = frappe.get_meta(DOCTYPE)
        fieldnames_in_order = [df.fieldname for df in meta.fields]
        anchor_index = fieldnames_in_order.index(ANCHOR_FIELDNAME)
        self.assertEqual(
            fieldnames_in_order[anchor_index + 1],
            FIELDNAME,
            "expected_deal_value must render immediately after annual_revenue",
        )

    def test_value_persists_on_real_lead_record(self):
        # Insert a real Lead document with the custom field populated.
        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Easytouch Expected Deal Value Test Lead",
                "email_id": "expected-deal-value-test@example.test",
                FIELDNAME: TEST_VALUE,
            }
        )
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        self.__class__.created_lead_name = lead.name

        # Reload the in-memory document from the database to clear any
        # cached/unsaved state, proving the value round-trips through the DB.
        lead.reload()
        self.assertEqual(float(lead.get(FIELDNAME)), TEST_VALUE)

        # Independently re-fetch a fresh document instance by name as a
        # second, unambiguous persistence check.
        reloaded = frappe.get_doc("Lead", self.created_lead_name)
        self.assertEqual(float(reloaded.get(FIELDNAME)), TEST_VALUE)


if __name__ == "__main__":
    unittest.main()
