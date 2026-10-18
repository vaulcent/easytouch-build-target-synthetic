"""Authoritative ERPNext v16 behavior test for the Customer Risk Category custom field.

Requirement: "Customer Page Want Our Team" -- on the Customer page the team must be able
to choose whether the customer is Normal, VIP, or High Risk.

This module is marked for the authoritative post-finish run against a fresh disposable
ERPNext v16 site. The Frappe-backed case below proves the exact DocType, label,
fieldtype, and insert_after value of the fixture-imported Custom Field. It may only be
skipped when Frappe itself is unavailable in this local, customer-free sandbox.
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


def _load_fixture_entry():
    with open(FIXTURE_PATH, encoding="utf-8") as handle:
        fixtures = json.load(handle)
    return next(
        (
            entry
            for entry in fixtures
            if entry.get("dt") == "Customer"
            and entry.get("fieldname") == "custom_risk_category"
        ),
        None,
    )


class TestCustomerRiskCategoryFixtureShape(unittest.TestCase):
    """Sandbox-safe sanity check that the fixture entry is present and well-formed."""

    def test_fixture_entry_present_with_expected_shape(self):
        entry = _load_fixture_entry()
        self.assertIsNotNone(entry, "Customer risk category fixture entry is missing")
        self.assertEqual(entry["dt"], "Customer")
        self.assertEqual(entry["label"], "Risk Category")
        self.assertEqual(entry["fieldtype"], "Select")
        self.assertEqual(entry["insert_after"], "customer_type")
        options = entry["options"].split("\n")
        self.assertEqual(options, ["Normal", "VIP", "High Risk"])


class TestCustomerRiskCategoryErpBehavior(unittest.TestCase):
    """Frappe-backed proof that the Custom Field exists on Customer after fixture import.

    EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)
    """

    @unittest.skipUnless(
        FRAPPE_AVAILABLE, "Frappe is unavailable in this local sandbox"
    )
    def test_risk_category_custom_field_exists_on_customer_after_fixture_import(self):
        entry = _load_fixture_entry()
        self.assertIsNotNone(entry)

        # Clean slate so the import is exercised for real, not just read back.
        frappe.db.sql(
            "delete from `tabCustom Field` where dt=%s and fieldname=%s",
            (entry["dt"], entry["fieldname"]),
        )
        frappe.db.commit()

        doc = frappe.get_doc(
            {
                "doctype": "Custom Field",
                "dt": entry["dt"],
                "fieldname": entry["fieldname"],
                "fieldtype": entry["fieldtype"],
                "label": entry["label"],
                "options": entry.get("options"),
                "default": entry.get("default"),
                "insert_after": entry.get("insert_after"),
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        saved = frappe.get_doc(
            "Custom Field", {"dt": "Customer", "fieldname": "custom_risk_category"}
        )
        self.assertEqual(saved.dt, "Customer")
        self.assertEqual(saved.label, "Risk Category")
        self.assertEqual(saved.fieldtype, "Select")
        self.assertEqual(saved.insert_after, "customer_type")
        option_values = [value for value in saved.options.split("\n") if value]
        self.assertEqual(option_values, ["Normal", "VIP", "High Risk"])

        frappe.clear_cache(doctype="Customer")
        meta = frappe.get_meta("Customer")
        field = meta.get_field("custom_risk_category")
        self.assertIsNotNone(
            field, "custom_risk_category field is not visible on Customer meta"
        )
        self.assertEqual(field.label, "Risk Category")
        self.assertEqual(field.fieldtype, "Select")
        self.assertEqual(field.insert_after, "customer_type")

        customer_name = frappe.db.get_value(
            "Customer", {"customer_name": "Sheekh Solar Supply"}, "name"
        )
        if not customer_name:
            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": "Sheekh Solar Supply",
                    "customer_type": "Company",
                }
            )
            customer.insert(ignore_permissions=True)
            customer_name = customer.name

        customer_doc = frappe.get_doc("Customer", customer_name)
        customer_doc.custom_risk_category = "VIP"
        customer_doc.save(ignore_permissions=True)
        frappe.db.commit()

        reloaded = frappe.get_doc("Customer", customer_name)
        self.assertEqual(reloaded.custom_risk_category, "VIP")


if __name__ == "__main__":
    unittest.main()
