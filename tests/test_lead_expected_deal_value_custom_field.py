"""Authoritative ERP-behavior evidence for the Lead "Expected Deal Value" custom field.

This module is the dedicated, marked suite for the requirement:
  Add a custom Currency field called "Expected Deal Value" to Lead, placed
  directly below Annual Revenue (insert_after = "annual_revenue").

It is loaded by `bench execute` against a real, disposable ERPNext v16 site
where Frappe and the installed `synthetic_build_target_app` fixtures are
available. In the local coding sandbox (no Frappe installed) the ERP-backed
cases are skipped via unittest.skipUnless; they must execute for real inside
the disposable validation site after finish.
"""

import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe  # type: ignore
    FRAPPE_AVAILABLE = True
except Exception:
    FRAPPE_AVAILABLE = False


def _ensure_site_context():
    """Reuse an active Frappe db connection if present, otherwise connect to
    the configured site. Mirrors how `bench execute` typically provides
    frappe.local.db already set, but tolerates a bare import as well.
    """
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    """Marked ERP behavior test: custom_field."""

    FIELDNAME = "expected_deal_value"
    DOCTYPE = "Lead"
    LABEL = "Expected Deal Value"
    ANCHOR = "annual_revenue"

    @classmethod
    def setUpClass(cls):
        _ensure_site_context()
        cls._created_lead_name = None

    @classmethod
    def tearDownClass(cls):
        if cls._created_lead_name:
            try:
                frappe.delete_doc("Lead", cls._created_lead_name, force=True, ignore_permissions=True)
                frappe.db.commit()
            except Exception:
                pass

    def test_exactly_one_currency_custom_field_installed_with_correct_metadata(self):
        """Prove exactly one Currency Custom Field exists on Lead with the
        requested label/fieldname/fieldtype, and that insert_after points
        directly at annual_revenue (not a chained custom field anchor)."""
        rows = frappe.get_all(
            "Custom Field",
            filters={"dt": self.DOCTYPE, "fieldname": self.FIELDNAME},
            fields=["name", "fieldtype", "label", "insert_after"],
        )
        self.assertEqual(
            len(rows), 1,
            f"Expected exactly one Custom Field row for {self.DOCTYPE}.{self.FIELDNAME}, got {rows}",
        )
        row = rows[0]
        self.assertEqual(row["fieldtype"], "Currency")
        self.assertEqual(row["label"], self.LABEL)
        self.assertEqual(row["insert_after"], self.ANCHOR)

        # No other custom field on Lead may share the same insert_after anchor,
        # which would make the rendered order non-deterministic.
        anchor_sharers = frappe.get_all(
            "Custom Field",
            filters={"dt": self.DOCTYPE, "insert_after": self.ANCHOR},
            fields=["fieldname"],
        )
        anchor_fieldnames = {r["fieldname"] for r in anchor_sharers}
        self.assertEqual(
            anchor_fieldnames, {self.FIELDNAME},
            f"Multiple fields anchored at '{self.ANCHOR}' makes order non-deterministic: {anchor_fieldnames}",
        )

    def test_field_is_rendered_immediately_after_annual_revenue_in_meta(self):
        """Reload real Lead metadata and assert the rendered fieldname order
        places expected_deal_value directly after annual_revenue."""
        meta = frappe.get_meta(self.DOCTYPE)
        fieldnames = [df.fieldname for df in meta.fields]

        self.assertIn(self.ANCHOR, fieldnames, "annual_revenue must exist on Lead")
        self.assertIn(self.FIELDNAME, fieldnames)

        anchor_index = fieldnames.index(self.ANCHOR)
        target_index = fieldnames.index(self.FIELDNAME)
        self.assertEqual(
            target_index, anchor_index + 1,
            f"expected_deal_value (index {target_index}) is not directly after "
            f"annual_revenue (index {anchor_index}) in rendered meta order: {fieldnames}",
        )

        df = meta.get_field(self.FIELDNAME)
        self.assertEqual(df.fieldtype, "Currency")
        self.assertEqual(df.label, self.LABEL)

    def test_value_persists_on_a_real_inserted_and_reloaded_lead(self):
        """Insert a real Lead with a value in the new field, then reload the
        same in-memory document from the database (doc.reload()) as well as
        via a fresh frappe.get_doc(), and verify the value round-trips both
        ways -- proving real persistence, not an in-memory artifact."""
        lead = frappe.get_doc({
            "doctype": "Lead",
            "lead_name": "Easytouch Expected Deal Value Test Lead",
            "email_id": "expected.deal.value.test@example.test",
            self.FIELDNAME: 12345.67,
        })
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        self.__class__._created_lead_name = lead.name

        # Clear the in-memory value, then reload the very same document
        # object from the database to prove the DB row (not Python state)
        # holds the value.
        lead.db_set(self.FIELDNAME, lead.get(self.FIELDNAME))
        lead_name = lead.name
        lead.set(self.FIELDNAME, None)
        lead.reload()
        self.assertEqual(float(lead.get(self.FIELDNAME)), 12345.67)

        # Independently fetch a brand new document instance for the same
        # record name to double-confirm persistence via a cold read.
        reloaded = frappe.get_doc("Lead", lead_name)
        self.assertEqual(float(reloaded.get(self.FIELDNAME)), 12345.67)


if __name__ == "__main__":
    unittest.main()
