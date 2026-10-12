"""Authoritative ERPNext v16 behavior evidence for the "Customer Risk
Classification" requirement: the team must be able to choose, on the
Customer page, whether a customer is Normal, VIP, or High Risk.

Proves, against a real disposable ERPNext v16 site, that after fixture
import the real Customer DocType metadata actually carries the
"risk_classification" Custom Field with the exact label, fieldtype,
options, default, and insert_after position described in
fixtures/custom_field.json -- not merely that the fixture file on disk
says so -- and that a real Customer document can actually be set to each
of the three allowed values (and rejects a value outside that set).

Loaded by ``bench execute`` with an active Frappe database context:
reuses ``frappe.local.db`` when already present, and only initializes
from ``frappe.local.site`` when needed. Skips only when Frappe itself is
unavailable in this local coding sandbox.
"""

from __future__ import annotations

import importlib.util
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

FRAPPE_AVAILABLE = importlib.util.find_spec("frappe") is not None


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; this authoritative "
    "case must run inside a real disposable ERPNext v16 site via "
    "bench execute.",
)
class TestCustomerRiskClassificationBehavior(unittest.TestCase):
    CUSTOMER_NAME = "Easytouch Risk Classification Behavior Test Customer"

    @classmethod
    def setUpClass(cls):
        import frappe

        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        cls.frappe = frappe
        frappe.set_user("Administrator")

        cls.customer_group = cls._ensure_leaf_customer_group()
        cls.territory = cls._ensure_leaf_territory()

    @classmethod
    def tearDownClass(cls):
        cls.frappe.set_user("Administrator")

    # -- master-data setup -------------------------------------------------

    @classmethod
    def _ensure_leaf_customer_group(cls):
        frappe = cls.frappe
        leaf = frappe.get_all(
            "Customer Group", filters={"is_group": 0}, pluck="name", limit=1
        )
        if leaf:
            return leaf[0]
        root = frappe.get_all(
            "Customer Group", filters={"is_group": 1}, pluck="name", limit=1
        )
        if root:
            root_name = root[0]
        else:
            root_doc = frappe.get_doc(
                {
                    "doctype": "Customer Group",
                    "customer_group_name": "All Customer Groups",
                    "is_group": 1,
                }
            )
            root_doc.insert(ignore_permissions=True)
            root_name = root_doc.name
        leaf_doc = frappe.get_doc(
            {
                "doctype": "Customer Group",
                "customer_group_name": "Easytouch Risk Classification Test Group",
                "is_group": 0,
                "parent_customer_group": root_name,
            }
        )
        leaf_doc.insert(ignore_permissions=True)
        return leaf_doc.name

    @classmethod
    def _ensure_leaf_territory(cls):
        frappe = cls.frappe
        leaf = frappe.get_all(
            "Territory", filters={"is_group": 0}, pluck="name", limit=1
        )
        if leaf:
            return leaf[0]
        root = frappe.get_all(
            "Territory", filters={"is_group": 1}, pluck="name", limit=1
        )
        if root:
            root_name = root[0]
        else:
            root_doc = frappe.get_doc(
                {
                    "doctype": "Territory",
                    "territory_name": "All Territories",
                    "is_group": 1,
                }
            )
            root_doc.insert(ignore_permissions=True)
            root_name = root_doc.name
        leaf_doc = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": "Easytouch Risk Classification Test Territory",
                "is_group": 0,
                "parent_territory": root_name,
            }
        )
        leaf_doc.insert(ignore_permissions=True)
        return leaf_doc.name

    def _ensure_customer(self):
        frappe = self.frappe
        if frappe.db.exists("Customer", self.CUSTOMER_NAME):
            return frappe.get_doc("Customer", self.CUSTOMER_NAME)
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": self.CUSTOMER_NAME,
                "customer_group": self.customer_group,
                "territory": self.territory,
                "customer_type": "Individual",
            }
        )
        customer.insert(ignore_permissions=True)
        frappe.db.commit()
        return customer

    # -- behavior tests ------------------------------------------------------

    def test_field_exists_on_live_customer_doctype_with_correct_metadata(self):
        frappe = self.frappe
        meta = frappe.get_meta("Customer")
        field = meta.get_field("risk_classification")

        self.assertIsNotNone(
            field,
            "the 'risk_classification' Custom Field must actually exist on "
            "the live Customer DocType metadata after fixture import, not "
            "only in the on-disk fixture file.",
        )
        self.assertEqual(field.label, "Risk Classification")
        self.assertEqual(field.fieldtype, "Select")
        self.assertEqual(
            [opt for opt in field.options.split("\n") if opt],
            ["Normal", "VIP", "High Risk"],
        )
        self.assertEqual(field.default, "Normal")
        self.assertEqual(field.insert_after, "customer_group")

    def test_team_can_set_each_allowed_value_on_a_real_customer(self):
        frappe = self.frappe
        customer = self._ensure_customer()

        self.assertEqual(
            customer.risk_classification,
            "Normal",
            "a newly created Customer must default to 'Normal'.",
        )

        for value in ("VIP", "High Risk", "Normal"):
            customer.risk_classification = value
            customer.save(ignore_permissions=True)
            frappe.db.commit()

            reloaded = frappe.get_doc("Customer", self.CUSTOMER_NAME)
            self.assertEqual(
                reloaded.risk_classification,
                value,
                f"team must be able to set Customer risk classification to "
                f"'{value}' and have it persist on the real document.",
            )

    def test_value_outside_the_allowed_set_is_rejected(self):
        frappe = self.frappe
        customer = self._ensure_customer()

        customer.risk_classification = "Not A Real Option"
        with self.assertRaises(frappe.exceptions.ValidationError):
            customer.save(ignore_permissions=True)

        unchanged = frappe.get_doc("Customer", self.CUSTOMER_NAME)
        self.assertIn(unchanged.risk_classification, ("Normal", "VIP", "High Risk"))


if __name__ == "__main__":
    unittest.main()
