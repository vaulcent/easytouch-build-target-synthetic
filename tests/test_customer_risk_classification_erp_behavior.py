"""Authoritative ERP-backed evidence for the Customer Risk Classification field.

This module is loaded by `bench execute` against a disposable, live ERPNext v16
site. It proves that after the app's Custom Field fixture is imported, the
real `Customer` DocType carries a `risk_classification` Select field with the
exact label/fieldtype/insert_after/options requested, and that the field is
actually usable on a real, inserted Customer document.

When Frappe is unavailable (the local coding sandbox), the ERP-backed cases
are skipped via unittest.skipUnless; they must execute for real once this
module runs inside an installed ERPNext v16 site.
"""

import unittest

try:
    import frappe

    FRAPPE_AVAILABLE = True
except ImportError:  # pragma: no cover - expected in the local coding sandbox
    FRAPPE_AVAILABLE = False

# Literal marker required by the deterministic completion contract.
EASYTOUCH_ERP_BEHAVIOR_KINDS = ("dashboard",)

APP_NAME = "synthetic_build_target_app"
DT = "Customer"
FIELDNAME = "risk_classification"
CUSTOM_FIELD_NAME = f"{DT}-{FIELDNAME}"
EXPECTED_LABEL = "Risk Classification"
EXPECTED_FIELDTYPE = "Select"
EXPECTED_INSERT_AFTER = "customer_type"
EXPECTED_OPTIONS = ["Normal", "VIP", "High Risk"]
TEST_CUSTOMER_NAME = "EASYTOUCH-RISK-TEST-CUSTOMER"


def _ensure_frappe_context():
    """Reuse the active bench execute DB context, or connect to the site."""
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


def _ensure_leaf(doctype, name_field, parent_field):
    """Return a non-group leaf record for a hierarchical master, creating one
    under the real tree root if no leaf already exists on this site."""
    leaf = frappe.db.get_value(doctype, {"is_group": 0}, "name")
    if leaf:
        return leaf

    root = frappe.db.get_value(doctype, {"is_group": 1}, "name")
    if not root:
        root = frappe.db.get_value(doctype, {}, "name")

    new_name = f"EASYTOUCH-RISK-TEST-{doctype.upper().replace(' ', '-')}"
    if frappe.db.exists(doctype, new_name):
        return new_name

    doc = frappe.get_doc(
        {
            "doctype": doctype,
            name_field: new_name,
            parent_field: root,
            "is_group": 0,
        }
    )
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is unavailable in this local sandbox")
class TestCustomerRiskClassificationErpBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_frappe_context()
        from frappe.utils.fixtures import sync_fixtures

        sync_fixtures(APP_NAME)
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        if frappe.db.exists(DT, TEST_CUSTOMER_NAME):
            frappe.delete_doc(DT, TEST_CUSTOMER_NAME, force=1, ignore_permissions=True)
            frappe.db.commit()

    def test_custom_field_imported_with_exact_metadata(self):
        self.assertTrue(
            frappe.db.exists("Custom Field", CUSTOM_FIELD_NAME),
            "Expected the Customer-risk_classification Custom Field to exist "
            "on the real site after fixture import.",
        )
        doc = frappe.get_doc("Custom Field", CUSTOM_FIELD_NAME)
        self.assertEqual(doc.dt, DT)
        self.assertEqual(doc.label, EXPECTED_LABEL)
        self.assertEqual(doc.fieldtype, EXPECTED_FIELDTYPE)
        self.assertEqual(doc.insert_after, EXPECTED_INSERT_AFTER)
        self.assertEqual(sorted(doc.options.split("\n")), sorted(EXPECTED_OPTIONS))

        # The field must actually be attached to the live Customer DocType
        # metadata used to render the customer page, not only the fixture row.
        meta = frappe.get_meta(DT)
        live_field = meta.get_field(FIELDNAME)
        self.assertIsNotNone(
            live_field, "risk_classification must appear in live Customer metadata"
        )
        self.assertEqual(live_field.label, EXPECTED_LABEL)
        self.assertEqual(live_field.fieldtype, EXPECTED_FIELDTYPE)
        self.assertEqual(sorted(live_field.options.split("\n")), sorted(EXPECTED_OPTIONS))

    def test_field_is_usable_on_a_real_customer_document(self):
        territory = _ensure_leaf("Territory", "territory_name", "parent_territory")
        customer_group = _ensure_leaf(
            "Customer Group", "customer_group_name", "parent_customer_group"
        )

        if frappe.db.exists(DT, TEST_CUSTOMER_NAME):
            frappe.delete_doc(DT, TEST_CUSTOMER_NAME, force=1, ignore_permissions=True)
            frappe.db.commit()

        customer = frappe.get_doc(
            {
                "doctype": DT,
                "customer_name": TEST_CUSTOMER_NAME,
                "customer_type": "Company",
                "territory": territory,
                "customer_group": customer_group,
                "risk_classification": "High Risk",
            }
        )
        customer.insert(ignore_permissions=True)
        frappe.db.commit()

        try:
            stored_value = frappe.db.get_value(
                DT, customer.name, "risk_classification"
            )
            self.assertEqual(
                stored_value,
                "High Risk",
                "The team's selected Risk Classification must persist on the "
                "real Customer document.",
            )

            reloaded = frappe.get_doc(DT, customer.name)
            self.assertEqual(reloaded.risk_classification, "High Risk")

            # Option enforcement: an out-of-list value must be rejected by
            # the real Select field validation on the live site.
            reloaded.risk_classification = "Not-A-Real-Option"
            with self.assertRaises(frappe.exceptions.ValidationError):
                reloaded.save(ignore_permissions=True)
        finally:
            frappe.delete_doc(DT, customer.name, force=1, ignore_permissions=True)
            frappe.db.commit()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
