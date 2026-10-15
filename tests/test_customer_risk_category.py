"""Authoritative ERPNext-backed evidence for the Customer Risk Category field.

Requirement: Customer Page Want Our Team -- the customer page must let the
team choose whether a Customer is Normal, VIP, or High Risk.

This module is the dedicated, compact, authoritative behavior-test module for
that change. It proves, against a real (disposable) ERPNext v16 site:

  * the exact Custom Field metadata (DocType, label, fieldtype, options,
    insert_after) after fixture import, and
  * that the field actually stores and returns the chosen value on a real
    Customer document (observable behavior, not just source/shape).

It intentionally skips -- rather than mocks -- when Frappe is unavailable in
this local sandbox, per the completion contract. Only a real Frappe/MariaDB
connection on the disposable ERPNext v16 site is used as evidence anywhere
in this module.
"""

import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("CUSTOM_FIELD",)

try:
    import frappe  # type: ignore

    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is unavailable in this local sandbox; authoritative evidence is "
    "produced in a fresh disposable ERPNext v16 site.",
)
class TestCustomerRiskCategoryField(unittest.TestCase):
    """Behavior evidence for the Customer -> Risk Category Select field."""

    TEST_CUSTOMER_NAME = "Easytouch Risk Category Test Customer"

    @classmethod
    def setUpClass(cls):
        frappe.init(site=frappe.local.site) if getattr(frappe, "local", None) else None
        frappe.connect()
        frappe.set_user("Administrator")

    @classmethod
    def tearDownClass(cls):
        if frappe.db.exists("Customer", cls.TEST_CUSTOMER_NAME):
            frappe.delete_doc(
                "Customer", cls.TEST_CUSTOMER_NAME, force=1, ignore_permissions=True
            )
            frappe.db.commit()

    def test_custom_field_metadata_matches_fixture_exactly(self):
        """The imported Custom Field must have the exact requested shape."""
        field_name = "Customer-risk_category"
        self.assertTrue(
            frappe.db.exists("Custom Field", field_name),
            "Expected Custom Field 'Customer-risk_category' to be present "
            "after fixture import.",
        )

        custom_field = frappe.get_doc("Custom Field", field_name)

        self.assertEqual(custom_field.dt, "Customer")
        self.assertEqual(custom_field.fieldname, "risk_category")
        self.assertEqual(custom_field.label, "Risk Category")
        self.assertEqual(custom_field.fieldtype, "Select")
        self.assertEqual(custom_field.insert_after, "customer_type")
        self.assertEqual(
            {opt.strip() for opt in custom_field.options.split("\n") if opt.strip()},
            {"Normal", "VIP", "High Risk"},
        )

        meta = frappe.get_meta("Customer")
        meta_field = meta.get_field("risk_category")
        self.assertIsNotNone(
            meta_field, "risk_category must be a live field on Customer meta."
        )
        self.assertEqual(meta_field.fieldtype, "Select")
        self.assertEqual(meta_field.label, "Risk Category")

    def test_team_can_choose_vip_and_value_persists(self):
        """A real Customer document must store the chosen risk category."""
        if frappe.db.exists("Customer", self.TEST_CUSTOMER_NAME):
            frappe.delete_doc(
                "Customer", self.TEST_CUSTOMER_NAME, force=1, ignore_permissions=True
            )
            frappe.db.commit()

        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": self.TEST_CUSTOMER_NAME,
                "customer_type": "Company",
                "risk_category": "VIP",
            }
        )
        customer.insert(ignore_permissions=True)
        frappe.db.commit()

        reloaded = frappe.get_doc("Customer", customer.name)
        self.assertEqual(reloaded.risk_category, "VIP")

        reloaded.risk_category = "High Risk"
        reloaded.save(ignore_permissions=True)
        frappe.db.commit()

        reloaded_again = frappe.get_doc("Customer", customer.name)
        self.assertEqual(reloaded_again.risk_category, "High Risk")


if __name__ == "__main__":
    unittest.main()
