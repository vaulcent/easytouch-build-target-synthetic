"""Authoritative ERP behavior test for the Lead "Expected Deal Value" custom field.

This module is executed in two contexts:

1. The local, Frappe-free coding sandbox, where Frappe is not installed and the
   single Frappe-backed test case is skipped via ``unittest.skipUnless``.
2. A real, disposable ERPNext v16 validation site (loaded via ``bench execute``
   with an already-active Frappe database context, backed by the real
   application database), where the test actually imports Frappe, reads live
   DocType metadata for ``Lead``, inserts a real Lead document, reloads it
   from the database, and asserts the persisted value.

No mocked Frappe, mocked database access, or source-text/fixture-shape checks
are used as evidence here.
"""

import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('custom_field',)

try:
    import frappe
    FRAPPE_AVAILABLE = True
except ImportError:
    frappe = None
    FRAPPE_AVAILABLE = False


class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    """Proves the Lead.expected_deal_value Custom Field is installed correctly
    and that a real Lead document persists a value in that field."""

    @classmethod
    def setUpClass(cls):
        if not FRAPPE_AVAILABLE:
            return
        # Reuse an already-active Frappe DB context (e.g. under `bench execute`);
        # only initialize/connect when no active context exists locally.
        if not getattr(frappe.local, "db", None):
            site = getattr(frappe.local, "site", None)
            if not site:
                raise RuntimeError(
                    "No active frappe.local.site/db context available to run "
                    "this ERP-backed test."
                )
            frappe.init(site=site)
            frappe.connect()
        frappe.set_user("Administrator")
        cls._created_lead_name = None

    @classmethod
    def tearDownClass(cls):
        if not FRAPPE_AVAILABLE:
            return
        if cls._created_lead_name:
            try:
                frappe.delete_doc(
                    "Lead", cls._created_lead_name, force=1, ignore_permissions=True
                )
                frappe.db.commit()
            except Exception:
                pass

    @unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not installed in this local sandbox")
    def test_expected_deal_value_field_metadata_and_persistence(self):
        meta = frappe.get_meta("Lead")
        fields = meta.fields

        # Locate the anchor field and the new field by fieldname.
        anchor_index = None
        new_field = None
        new_field_index = None
        anchor_users = []  # fields whose insert_after == "annual_revenue"

        for idx, df in enumerate(fields):
            if df.fieldname == "annual_revenue":
                anchor_index = idx
            if df.fieldname == "expected_deal_value":
                new_field = df
                new_field_index = idx
            if getattr(df, "insert_after", None) == "annual_revenue":
                anchor_users.append(df.fieldname)

        self.assertIsNotNone(
            anchor_index, "Lead DocType must have an 'annual_revenue' field to anchor to."
        )
        self.assertIsNotNone(
            new_field,
            "Expected custom field 'expected_deal_value' was not found on Lead metadata.",
        )

        # Exact type, label, and insert_after.
        self.assertEqual(new_field.fieldtype, "Currency")
        self.assertEqual(new_field.label, "Expected Deal Value")
        self.assertEqual(new_field.insert_after, "annual_revenue")
        self.assertEqual(new_field.fieldname, "expected_deal_value")

        # Only one field anchors directly after annual_revenue (determinism).
        self.assertEqual(
            anchor_users,
            ["expected_deal_value"],
            "Exactly one field (expected_deal_value) must be anchored at "
            "insert_after='annual_revenue'; found: %r" % anchor_users,
        )

        # Rendered order: the new field must sit immediately after the anchor
        # in the meta's resolved field order.
        self.assertEqual(
            new_field_index,
            anchor_index + 1,
            "expected_deal_value must be rendered directly after annual_revenue "
            "(anchor_index=%s, field_index=%s)" % (anchor_index, new_field_index),
        )

        # --- Real persistence proof: insert a Lead, set the value, reload
        # the row from the live application database, and assert it stuck. ---
        lead = frappe.get_doc(
            {
                "doctype": "Lead",
                "lead_name": "Easytouch Expected Deal Value Test Lead",
                "email_id": "vaulcent143+expected-deal-value@gmail.com",
                "expected_deal_value": 125000,
            }
        )
        lead.insert(ignore_permissions=True)
        frappe.db.commit()
        self.__class__._created_lead_name = lead.name

        # Clear any in-memory cache for this doc and fetch a fresh instance
        # straight from the database to prove the value was actually persisted,
        # not merely held on the in-memory object that performed the insert.
        frappe.clear_document_cache("Lead", lead.name)
        reloaded = frappe.get_doc("Lead", lead.name)
        self.assertEqual(float(reloaded.expected_deal_value), 125000.0)

        # Mutate and reload a second time via doc.reload() to further confirm
        # round-trip persistence through an update cycle.
        reloaded.expected_deal_value = 250000
        reloaded.save(ignore_permissions=True)
        frappe.db.commit()
        reloaded.reload()
        self.assertEqual(float(reloaded.expected_deal_value), 250000.0)


if __name__ == "__main__":
    unittest.main()
