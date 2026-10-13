import ast
import json
import os
import types
import unittest

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_PATH = os.path.join(APP_ROOT, "synthetic_build_target_app", "hooks.py")
VALIDATION_MODULE_PATH = os.path.join(
    APP_ROOT,
    "synthetic_build_target_app",
    "synthetic_build_target_app",
    "sales_invoice_validations.py",
)
ROLE_FIXTURE_PATH = os.path.join(
    APP_ROOT, "synthetic_build_target_app", "fixtures", "role.json"
)
EXPECTED_DOTTED_PATH = (
    "synthetic_build_target_app.synthetic_build_target_app."
    "sales_invoice_validations.validate_selling_rate_against_valuation_rate"
)
AUTHORIZED_OVERRIDE_ROLE = "Sales Invoice Rate Override"

# Authoritative, Frappe-backed ERPNext v16 behavior evidence for this
# requirement (both the "validate" and "before_submit" lanes, the
# currency/Sales-UOM-aware comparison, and the override-role bypass) lives
# in the dedicated tests/test_sales_invoice_rate_validation_behavior.py
# module, not here. This module only contains static, sandbox-safe checks
# on the smallest complete wiring change (hooks.py doc_events + the
# validation module + the idempotent Role fixture).


def _load_hooks_module():
    with open(HOOKS_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    module = types.ModuleType("hooks_under_test")
    exec(compile(source, HOOKS_PATH, "exec"), module.__dict__)
    return module


class TestSalesInvoiceRateValidationWiring(unittest.TestCase):
    """Static checks that both validation lanes are correctly configured.

    These checks do not require Frappe and therefore run unconditionally in
    this sandbox; they verify the smallest complete wiring change in
    hooks.py and the presence/shape of the validation function.
    """

    @classmethod
    def setUpClass(cls):
        cls.hooks = _load_hooks_module()
        with open(VALIDATION_MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.validation_source = handle.read()
        cls.validation_ast = ast.parse(cls.validation_source)

    def test_doc_events_defined_for_sales_invoice(self):
        self.assertTrue(hasattr(self.hooks, "doc_events"))
        self.assertIn("Sales Invoice", self.hooks.doc_events)

    def test_both_validation_lanes_configured(self):
        events = self.hooks.doc_events["Sales Invoice"]
        self.assertIn(
            "validate",
            events,
            "Expected a 'validate' (save-time) validation lane for Sales Invoice.",
        )
        self.assertIn(
            "before_submit",
            events,
            "Expected a 'before_submit' (submit-time) validation lane for "
            "Sales Invoice.",
        )
        self.assertEqual(events["validate"], EXPECTED_DOTTED_PATH)
        self.assertEqual(events["before_submit"], EXPECTED_DOTTED_PATH)

    def test_hooked_doctypes_are_real_submittable_stock_transactions(self):
        # hooks.py also wires on_submit/on_cancel hooks for the Important
        # Item Low Stock Alert (a separate real ERPNext semantic gap
        # repaired alongside this one). Real validation proved ERPNext's
        # internally written Stock Ledger Entry rows never emit on_submit
        # document events (they are inserted via a direct db_insert), so
        # that ineffective hook must NOT be present; instead every real,
        # originating transaction whose lifecycle changes Bin quantities
        # is hooked (Sales Invoice and Purchase Invoice only actually move
        # stock when update_stock is enabled, which the hooked function
        # itself gates on).
        self.assertEqual(
            set(self.hooks.doc_events.keys()),
            {
                "Sales Invoice",
                "Purchase Invoice",
                "Stock Entry",
                "Delivery Note",
                "Purchase Receipt",
                "Stock Reconciliation",
            },
        )
        self.assertNotIn("Stock Ledger Entry", self.hooks.doc_events)

    def test_validation_function_is_defined(self):
        function_names = [
            node.name
            for node in ast.walk(self.validation_ast)
            if isinstance(node, ast.FunctionDef)
        ]
        self.assertIn("validate_selling_rate_against_valuation_rate", function_names)

    def test_authorized_override_role_constant_defined(self):
        self.assertIn("AUTHORIZED_OVERRIDE_ROLE", self.validation_source)
        self.assertIn('"Sales Invoice Rate Override"', self.validation_source)

    def test_validation_compares_base_rate_to_valuation_floor_per_sales_uom(self):
        # Smallest-complete-change sanity check on the currency/Sales-UOM
        # aware comparison logic: selling rate converted to Company
        # currency (base_rate) compared against the per-Stock-UOM
        # valuation_rate scaled up by conversion_factor (Stock-UOM units
        # per one Sales-UOM unit) into a per-Sales-UOM floor.
        self.assertIn("valuation_rate", self.validation_source)
        self.assertIn("base_rate", self.validation_source)
        self.assertIn("conversion_factor", self.validation_source)
        self.assertIn(
            "base_rate < valuation_floor_per_sales_uom", self.validation_source
        )
        self.assertIn(
            "valuation_floor_per_sales_uom = valuation_rate * conversion_factor",
            self.validation_source,
        )

    def test_validation_falls_back_to_real_warehouse_bin_valuation_rate(self):
        # When a row's own valuation_rate is empty, the validation must
        # read the real warehouse Bin valuation_rate by item_code + the
        # row's own warehouse, rather than skipping the check.
        function_names = [
            node.name
            for node in ast.walk(self.validation_ast)
            if isinstance(node, ast.FunctionDef)
        ]
        self.assertIn("_get_warehouse_bin_valuation_rate", function_names)
        self.assertIn('"Bin"', self.validation_source)
        self.assertIn('"valuation_rate"', self.validation_source)
        self.assertIn('item.get("warehouse")', self.validation_source)
        self.assertIn('item.get("item_code")', self.validation_source)

    def test_fixtures_include_custom_field_and_role_override(self):
        fixtures = getattr(self.hooks, "fixtures", None)
        self.assertIn("Custom Field", fixtures)
        role_fixtures = [
            entry
            for entry in fixtures
            if isinstance(entry, dict) and entry.get("doctype") == "Role"
        ]
        self.assertEqual(
            len(role_fixtures),
            1,
            "Expected exactly one Role fixture entry provisioning the "
            "override role.",
        )
        filters = role_fixtures[0].get("filters")
        self.assertIn(["name", "=", AUTHORIZED_OVERRIDE_ROLE], filters)


class TestSalesInvoiceRateOverrideRoleFixture(unittest.TestCase):
    """The override Role must be an idempotent Frappe fixture file."""

    @classmethod
    def setUpClass(cls):
        with open(ROLE_FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _role_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Role"
            and entry.get("name") == AUTHORIZED_OVERRIDE_ROLE
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_role_exists_exactly_once(self):
        entries = self._role_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Sales Invoice Rate Override' Role "
            "fixture (idempotent - no duplicates).",
        )

    def test_role_definition(self):
        entry = self._role_entries()[0]
        self.assertEqual(entry["role_name"], AUTHORIZED_OVERRIDE_ROLE)
        self.assertEqual(entry["name"], AUTHORIZED_OVERRIDE_ROLE)


if __name__ == "__main__":
    unittest.main()
