import ast
import importlib.util
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

    def test_sales_invoice_and_stock_ledger_entry_doctypes_are_hooked(self):
        # hooks.py now also wires a Stock Ledger Entry -- on_submit hook for
        # the Important Item Low Stock Alert (a separate real ERPNext
        # semantic gap repaired alongside this one); both doctypes, and
        # only these two, are hooked.
        self.assertEqual(
            set(self.hooks.doc_events.keys()),
            {"Sales Invoice", "Stock Ledger Entry"},
        )

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

    def test_validation_compares_rate_to_valuation_rate(self):
        # Smallest-complete-change sanity check on the comparison logic.
        self.assertIn("valuation_rate", self.validation_source)
        self.assertIn("selling_rate < valuation_rate", self.validation_source)

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


class TestSalesInvoiceRateValidationFrappeBacked(unittest.TestCase):
    """Behavioral evidence requires a real Frappe/ERPNext v16 site.

    Frappe is intentionally unavailable in this local sandbox, so this case
    skips here. The authoritative post-finish run on a disposable ERPNext
    v16 site must exercise this with real Frappe/ERPNext (no SQLite or
    mocked Frappe), confirming that:
      - a non-override user cannot submit a Sales Invoice whose item rate
        is below its valuation rate -- including when the row's own
        valuation_rate is left empty and must be read from the real
        warehouse Bin instead -- (before_submit lane blocks it), and
      - a user holding the "Sales Invoice Rate Override" role (assignable
        because the role fixture provisions it) can submit it.
    """

    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec("frappe") is None:
            raise unittest.SkipTest(
                "Frappe is not installed in this local sandbox; behavioral "
                "evidence must come from a real ERPNext v16 site run."
            )

    def test_placeholder_requires_real_frappe_site(self):
        self.skipTest(
            "Run against a disposable ERPNext v16 site for authoritative "
            "evidence; not executed in this local sandbox."
        )


if __name__ == "__main__":
    unittest.main()
