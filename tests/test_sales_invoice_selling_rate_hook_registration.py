"""Dependency-free static check that the Sales Invoice selling-rate-vs-
valuation-rate validation is wired up correctly in hooks.py and that the
"Selling Rate Override" Role fixture is correctly configured.

This test does NOT require Frappe and is not, by itself, ERP behavior
evidence. The authoritative ERP-backed behavior proof lives in
tests/test_sales_invoice_selling_rate_validation.py (marked with
EASYTOUCH_ERP_BEHAVIOR_KINDS).
"""
import importlib
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class SalesInvoiceSellingRateHookRegistrationTests(unittest.TestCase):
    def test_validate_hook_is_registered_for_sales_invoice(self):
        hooks = importlib.import_module("synthetic_build_target_app.hooks")
        doc_events = getattr(hooks, "doc_events", {})
        self.assertIn("Sales Invoice", doc_events)
        self.assertEqual(
            doc_events["Sales Invoice"].get("validate"),
            "synthetic_build_target_app.sales_invoice_rate_validation."
            "validate_selling_rate_against_valuation",
        )
        # The pre-existing Project automation on_submit hook must be
        # preserved, unchanged, alongside the new validate hook.
        self.assertEqual(
            doc_events["Sales Invoice"].get("on_submit"),
            "synthetic_build_target_app.sales_invoice_events.create_project_from_sales_invoice",
        )

    def test_role_fixture_is_filtered_to_only_the_override_role(self):
        hooks = importlib.import_module("synthetic_build_target_app.hooks")
        fixtures = getattr(hooks, "fixtures", [])
        self.assertIn("Custom Field", fixtures)

        role_fixture_entries = [
            entry for entry in fixtures
            if isinstance(entry, dict) and entry.get("dt") == "Role"
        ]
        self.assertEqual(len(role_fixture_entries), 1)
        self.assertEqual(
            role_fixture_entries[0]["filters"], [["name", "=", "Selling Rate Override"]]
        )

    def test_role_fixture_file_defines_the_override_role(self):
        role_fixture_path = os.path.join(
            REPO_ROOT, "synthetic_build_target_app", "fixtures", "role.json"
        )
        with open(role_fixture_path, "r", encoding="utf-8") as fh:
            roles = json.load(fh)
        self.assertEqual(len(roles), 1)
        role = roles[0]
        self.assertEqual(role["doctype"], "Role")
        self.assertEqual(role["name"], "Selling Rate Override")
        self.assertEqual(role["role_name"], "Selling Rate Override")

    def test_handler_module_is_importable_without_frappe_and_exposes_functions(self):
        module = importlib.import_module(
            "synthetic_build_target_app.sales_invoice_rate_validation"
        )
        self.assertTrue(callable(module.validate_selling_rate_against_valuation))
        self.assertEqual(module.OVERRIDE_ROLE, "Selling Rate Override")

    def test_floor_per_sales_uom_multiplies_valuation_rate_by_conversion_factor(self):
        module = importlib.import_module(
            "synthetic_build_target_app.sales_invoice_rate_validation"
        )
        # valuation_rate=100 (USD per Stock UOM), conversion_factor=10
        # (10 Stock-UOM units per 1 Sales-UOM unit) -> floor per Sales UOM
        # is 1000, not 10 (which would be the wrong, inverted direction).
        self.assertEqual(module.get_floor_per_sales_uom(100, 10), 1000)


if __name__ == "__main__":
    unittest.main()
