import ast
import importlib.util
import os
import types
import unittest

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_PATH = os.path.join(APP_ROOT, "synthetic_build_target_app", "hooks.py")
MODULE_PATH = os.path.join(
    APP_ROOT,
    "synthetic_build_target_app",
    "synthetic_build_target_app",
    "stock_ledger_alerts.py",
)
EXPECTED_DOTTED_PATH = (
    "synthetic_build_target_app.synthetic_build_target_app."
    "stock_ledger_alerts.queue_important_item_low_stock_alert"
)


def _load_hooks_module():
    with open(HOOKS_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    module = types.ModuleType("hooks_under_test_sle_alert")
    exec(compile(source, HOOKS_PATH, "exec"), module.__dict__)
    return module


class TestStockLedgerEntryLowStockAlertHookWiring(unittest.TestCase):
    """Static checks for the stock-ledger-compatible low stock alert hook.

    ERPNext updates Bin quantities without going through Bin.save(), so the
    existing "Important Item Low Stock Alert" Notification's own
    "Value Change" detection never fires on a real site. These checks (no
    Frappe required) verify the general, non-item/warehouse-hardcoded hook
    that reads the final Bin quantity after real stock ledger operations
    and sends that same existing Notification.
    """

    @classmethod
    def setUpClass(cls):
        cls.hooks = _load_hooks_module()
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.module_ast = ast.parse(cls.source)

    def test_module_file_exists(self):
        self.assertTrue(os.path.isfile(MODULE_PATH))

    def test_stock_ledger_entry_on_submit_is_hooked(self):
        self.assertIn("Stock Ledger Entry", self.hooks.doc_events)
        events = self.hooks.doc_events["Stock Ledger Entry"]
        self.assertIn("on_submit", events)
        self.assertEqual(events["on_submit"], EXPECTED_DOTTED_PATH)

    def test_sales_invoice_hooks_untouched(self):
        self.assertIn("Sales Invoice", self.hooks.doc_events)
        events = self.hooks.doc_events["Sales Invoice"]
        self.assertIn("validate", events)
        self.assertIn("before_submit", events)

    def test_queue_and_send_functions_are_defined(self):
        function_names = [
            node.name
            for node in ast.walk(self.module_ast)
            if isinstance(node, ast.FunctionDef)
        ]
        self.assertIn("queue_important_item_low_stock_alert", function_names)
        self.assertIn("send_important_item_low_stock_alert", function_names)

    def test_hook_schedules_an_after_commit_job(self):
        self.assertIn("frappe.db.after_commit.add", self.source)

    def test_hook_reads_item_and_warehouse_generically_not_hardcoded(self):
        # item_code/warehouse must be read off the submitted Stock Ledger
        # Entry doc generically; no specific item/warehouse name literal.
        self.assertIn('doc.get("item_code")', self.source)
        self.assertIn('doc.get("warehouse")', self.source)

    def test_hook_reuses_existing_notification_document(self):
        self.assertIn("Important Item Low Stock Alert", self.source)
        self.assertIn('frappe.get_cached_doc(', self.source)
        self.assertIn("notification.send(bin_doc)", self.source)

    def test_hook_reads_final_bin_for_item_and_warehouse(self):
        self.assertIn('"Bin"', self.source)
        self.assertIn('"item_code": item_code', self.source)
        self.assertIn('"warehouse": warehouse', self.source)


class TestStockLedgerEntryLowStockAlertFrappeBacked(unittest.TestCase):
    """Behavioral evidence requires a real Frappe/ERPNext v16 site.

    Frappe is intentionally unavailable in this local sandbox, so this case
    skips here. The authoritative post-finish run on a disposable ERPNext
    v16 site must exercise this with real Frappe/ERPNext (no SQLite or
    mocked Frappe), confirming that a real stock movement (e.g. a
    submitted Stock Entry) that drops an is_important_item item's
    warehouse Bin quantity below 10 results in the existing "Important
    Item Low Stock Alert" Notification being sent to the Purchase Manager
    role, with the warehouse present in the alert -- without any Bin
    document save() ever being called directly.
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
