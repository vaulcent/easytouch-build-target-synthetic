"""No-Frappe-required checks for the Sales Invoice -> Project auto-create
hook wiring and logic.

These checks verify (without any Frappe installation) that:

1. hooks.py wires the real create_project_for_submitted_sales_invoice
   handler onto Sales Invoice's real "on_submit" document event,
   alongside (not replacing) the existing low-stock-alert on_submit
   handler, and that the validate/before_submit rate-validation hooks are
   left untouched.
2. The real create_project_for_submitted_sales_invoice function body
   (loaded from disk and executed against a minimal controlled "frappe"
   stand-in, not re-typed) builds the Project name from the invoice's
   customer name and invoice number, links the new Project back to the
   Sales Invoice via the "sales_invoice" field, and is idempotent: a
   second call for the same invoice must not insert a second Project.

The authoritative, Frappe-backed proof that this fires on a real
submitted Sales Invoice document-lifecycle event and actually creates a
real, linked Project lives in
tests/test_sales_invoice_submission_creates_project_behavior.py.
"""

import os
import types
import unittest
import importlib.util
import sys

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_PATH = os.path.join(APP_ROOT, "synthetic_build_target_app", "hooks.py")
MODULE_PATH = os.path.join(
    APP_ROOT,
    "synthetic_build_target_app",
    "synthetic_build_target_app",
    "sales_invoice_project.py",
)
EXPECTED_DOTTED_PATH = (
    "synthetic_build_target_app.synthetic_build_target_app."
    "sales_invoice_project.create_project_for_submitted_sales_invoice"
)


def _load_hooks_module():
    with open(HOOKS_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    module = types.ModuleType("hooks_under_test_sales_invoice_project")
    exec(compile(source, HOOKS_PATH, "exec"), module.__dict__)
    return module


class TestSalesInvoiceProjectHookWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hooks = _load_hooks_module()

    def test_module_file_exists(self):
        self.assertTrue(os.path.isfile(MODULE_PATH))

    def test_on_submit_includes_project_creation_handler(self):
        events = self.hooks.doc_events["Sales Invoice"]
        self.assertIn("on_submit", events)
        on_submit = events["on_submit"]
        self.assertIsInstance(on_submit, (list, tuple))
        self.assertIn(EXPECTED_DOTTED_PATH, on_submit)

    def test_existing_low_stock_alert_on_submit_handler_untouched(self):
        on_submit = self.hooks.doc_events["Sales Invoice"]["on_submit"]
        self.assertIn(
            "synthetic_build_target_app.synthetic_build_target_app."
            "stock_ledger_alerts.queue_important_item_low_stock_alert",
            on_submit,
        )

    def test_validate_and_before_submit_hooks_untouched(self):
        events = self.hooks.doc_events["Sales Invoice"]
        expected = (
            "synthetic_build_target_app.synthetic_build_target_app."
            "sales_invoice_validations.validate_selling_rate_against_valuation_rate"
        )
        self.assertEqual(events["validate"], expected)
        self.assertEqual(events["before_submit"], expected)

    def test_other_doctype_hooks_untouched(self):
        for doctype in ("Stock Entry", "Delivery Note", "Purchase Receipt"):
            self.assertIn(doctype, self.hooks.doc_events)
            self.assertIn("on_submit", self.hooks.doc_events[doctype])


class _FakeProjectDoc:
    def __init__(self, fields):
        self.fields = fields
        self.inserted = False
        self.name = fields.get("project_name")

    def insert(self, ignore_permissions=False):
        self.inserted = True


class _FakeFrappeDB:
    def __init__(self):
        self.projects_by_sales_invoice = {}

    def get_value(self, doctype, filters, fieldname=None):
        assert doctype == "Project"
        sales_invoice = filters.get("sales_invoice")
        return self.projects_by_sales_invoice.get(sales_invoice)


class _FakeFrappe:
    def __init__(self):
        self.db = _FakeFrappeDB()
        self.created_docs = []

    def get_doc(self, fields):
        doc = _FakeProjectDoc(fields)
        self.created_docs.append(doc)
        return doc


def _load_module_against_fake_frappe(fake_frappe):
    previous_frappe = sys.modules.get("frappe")
    sys.modules["frappe"] = fake_frappe
    try:
        spec = importlib.util.spec_from_file_location(
            "sales_invoice_project_under_test_%d" % id(fake_frappe), MODULE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous_frappe is not None:
            sys.modules["frappe"] = previous_frappe
        else:
            del sys.modules["frappe"]
    return module


class _FakeSalesInvoice(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


class TestCreateProjectForSubmittedSalesInvoiceLogic(unittest.TestCase):
    def test_creates_project_named_from_customer_and_invoice_number(self):
        fake_frappe = _FakeFrappe()
        module = _load_module_against_fake_frappe(fake_frappe)

        invoice = _FakeSalesInvoice(
            name="SINV-0001",
            customer_name="Sheekh Solar Supply",
            customer="CUST-0001",
            company="Test Co",
        )

        module.create_project_for_submitted_sales_invoice(invoice)

        self.assertEqual(len(fake_frappe.created_docs), 1)
        created = fake_frappe.created_docs[0]
        self.assertTrue(created.inserted)
        self.assertEqual(created.fields["doctype"], "Project")
        self.assertEqual(created.fields["sales_invoice"], "SINV-0001")
        self.assertIn("Sheekh Solar Supply", created.fields["project_name"])
        self.assertIn("SINV-0001", created.fields["project_name"])

    def test_idempotent_skips_second_project_for_same_invoice(self):
        fake_frappe = _FakeFrappe()
        module = _load_module_against_fake_frappe(fake_frappe)

        invoice = _FakeSalesInvoice(
            name="SINV-0002",
            customer_name="Another Customer",
            customer="CUST-0002",
            company="Test Co",
        )

        module.create_project_for_submitted_sales_invoice(invoice)
        self.assertEqual(len(fake_frappe.created_docs), 1)

        # Simulate the Project now existing for this invoice.
        fake_frappe.db.projects_by_sales_invoice["SINV-0002"] = "PROJ-0001"

        module.create_project_for_submitted_sales_invoice(invoice)
        self.assertEqual(
            len(fake_frappe.created_docs),
            1,
            "a second call for the same invoice must not insert another "
            "Project",
        )


if __name__ == "__main__":
    unittest.main()
