"""Dependency-free static check that the Sales Invoice -> Project automation
is wired up correctly in hooks.py.

This test does NOT require Frappe and is not, by itself, ERP behavior
evidence. The authoritative ERP-backed behavior proof lives in
tests/test_sales_invoice_project_automation.py (marked with
EASYTOUCH_ERP_BEHAVIOR_KINDS).
"""
import importlib
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class SalesInvoiceProjectHookRegistrationTests(unittest.TestCase):
    def test_on_submit_hook_is_registered_for_sales_invoice(self):
        hooks = importlib.import_module("synthetic_build_target_app.hooks")
        doc_events = getattr(hooks, "doc_events", {})
        self.assertIn("Sales Invoice", doc_events)
        self.assertEqual(
            doc_events["Sales Invoice"].get("on_submit"),
            "synthetic_build_target_app.sales_invoice_events.create_project_from_sales_invoice",
        )

    def test_handler_module_is_importable_without_frappe_and_exposes_functions(self):
        module = importlib.import_module("synthetic_build_target_app.sales_invoice_events")
        self.assertTrue(callable(module.create_project_from_sales_invoice))
        self.assertTrue(callable(module.build_project_name))

    def test_build_project_name_uses_customer_and_invoice_number(self):
        module = importlib.import_module("synthetic_build_target_app.sales_invoice_events")

        class FakeInvoice:
            name = "ACC-SINV-2026-00042"
            customer = "CUST-0001"
            customer_name = "Nasiib Trading Co."

        self.assertEqual(
            module.build_project_name(FakeInvoice()),
            "Nasiib Trading Co. - ACC-SINV-2026-00042",
        )


if __name__ == "__main__":
    unittest.main()
