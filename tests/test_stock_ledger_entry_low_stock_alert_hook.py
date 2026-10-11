import ast
import importlib.util
import os
import sys
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

#: Real submittable stock transactions this hook must be wired to.
EXPECTED_HOOKED_DOCTYPES = (
    "Stock Entry",
    "Delivery Note",
    "Purchase Receipt",
    "Sales Invoice",
)


def _load_hooks_module():
    with open(HOOKS_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    module = types.ModuleType("hooks_under_test_sle_alert")
    exec(compile(source, HOOKS_PATH, "exec"), module.__dict__)
    return module


class TestStockTransactionLowStockAlertHookWiring(unittest.TestCase):
    """Static checks for the real-stock-transaction low stock alert hook.

    Real validation proved that ERPNext's internally written Stock Ledger
    Entry rows are inserted via a direct ``db_insert`` as part of posting a
    stock transaction, and never go through ``on_submit`` document-event
    dispatch themselves -- so a "Stock Ledger Entry" -- "on_submit" hook is
    never actually called on a real site and must not be preserved. These
    checks (no Frappe required) verify the repaired hook instead targets
    ``on_submit`` of the real, originating submittable stock transactions
    (Stock Entry, Delivery Note, Purchase Receipt, Sales Invoice), reads
    the final Bin quantity after real stock operations, and sends the
    existing Notification using ordinary trusted Python gating -- never a
    Notification condition evaluated via frappe.safe_eval, and never
    Notification.send's own (nonexistent) condition evaluation.
    """

    @classmethod
    def setUpClass(cls):
        cls.hooks = _load_hooks_module()
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.module_ast = ast.parse(cls.source)

    def test_module_file_exists(self):
        self.assertTrue(os.path.isfile(MODULE_PATH))

    def test_stock_ledger_entry_hook_is_not_preserved(self):
        # The ineffective Stock Ledger Entry on_submit hook must be
        # removed entirely, not merely left alongside the real fix.
        self.assertNotIn("Stock Ledger Entry", self.hooks.doc_events)

    def test_real_stock_transactions_on_submit_are_hooked(self):
        for doctype in EXPECTED_HOOKED_DOCTYPES:
            self.assertIn(doctype, self.hooks.doc_events)
            events = self.hooks.doc_events[doctype]
            self.assertIn("on_submit", events)
            on_submit = events["on_submit"]
            if isinstance(on_submit, (list, tuple)):
                # Sales Invoice's real on_submit event also fires the
                # separate "create a Project for this invoice" hook (see
                # sales_invoice_project.py); this low-stock-alert hook
                # must still be one of the real handlers wired to it.
                self.assertIn(EXPECTED_DOTTED_PATH, on_submit)
            else:
                self.assertEqual(on_submit, EXPECTED_DOTTED_PATH)

    def test_sales_invoice_validate_and_before_submit_hooks_untouched(self):
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
        # item_code/warehouse must be read off the submitted transaction's
        # rows generically; no specific item/warehouse name literal, and
        # every real warehouse field shape (plain "warehouse" as well as
        # Stock Entry's s_warehouse/t_warehouse) must be covered.
        self.assertIn('row.get("item_code")', self.source)
        self.assertIn('"warehouse"', self.source)
        self.assertIn('"s_warehouse"', self.source)
        self.assertIn('"t_warehouse"', self.source)

    def test_hook_reuses_existing_notification_document(self):
        self.assertIn("Important Item Low Stock Alert", self.source)
        self.assertIn("frappe.get_cached_doc(", self.source)
        self.assertIn("notification.send(bin_doc)", self.source)

    def test_hook_reads_final_bin_for_item_and_warehouse(self):
        self.assertIn('"Bin"', self.source)
        self.assertIn('"item_code": item_code', self.source)
        self.assertIn('"warehouse": warehouse', self.source)

    def test_hook_never_evaluates_notification_condition_via_safe_eval(self):
        # Notification.send(doc) never evaluates Notification.condition on
        # its own, and frappe.db access from inside a safe_eval'd
        # condition is forbidden, so this module must never attempt to
        # actually evaluate the stored condition string itself (the
        # explanatory module docstring may still mention safe_eval in
        # prose, so these checks look for the actual call/attribute
        # patterns a real evaluation attempt would use).
        self.assertNotIn("frappe.safe_eval(", self.source)
        self.assertNotIn("notification.condition", self.source)
        self.assertNotIn("import get_context", self.source)

    def test_hook_gates_in_trusted_python_on_item_flag_and_bin_quantity(self):
        # The actual important-item + low-stock gating must be ordinary
        # trusted Python: a direct Item.is_important_item lookup and a
        # direct comparison against the final Bin.actual_qty.
        self.assertIn("is_important_item", self.source)
        self.assertIn("LOW_STOCK_THRESHOLD", self.source)
        self.assertIn("bin_doc.actual_qty", self.source)
        self.assertIn(
            'frappe.db.get_value("Item", item_code, "is_important_item")',
            self.source,
        )


class _FakeNotification:
    """Records every document send_important_item_low_stock_alert sends."""

    def __init__(self, enabled=1):
        self.enabled = enabled
        self.sent_with = []

    def send(self, doc):
        self.sent_with.append(doc)


class _FakeBin:
    def __init__(self, name, actual_qty):
        self.name = name
        self.actual_qty = actual_qty


class _FakeFrappeDB:
    """Minimal frappe.db stand-in that records lookup call ordering."""

    def __init__(self, bin_name, item_important_value):
        self._bin_name = bin_name
        self._item_important_value = item_important_value
        self.after_commit = types.SimpleNamespace(add=lambda callback: None)
        self.item_lookup_calls = []
        self.bin_lookup_calls = []

    def exists(self, doctype, name):
        assert doctype == "Notification"
        return True

    def get_value(self, doctype, filters, fieldname=None):
        if doctype == "Bin":
            self.bin_lookup_calls.append((filters, fieldname))
            return self._bin_name
        if doctype == "Item":
            # Real call shape: frappe.db.get_value("Item", item_code,
            # "is_important_item") -- recorded here so tests can prove
            # whether this Item lookup was ever reached relative to the
            # LOW_STOCK_THRESHOLD comparison on the Bin quantity.
            self.item_lookup_calls.append((filters, fieldname))
            return self._item_important_value
        raise AssertionError("unexpected doctype in get_value: %s" % doctype)


class _FakeFrappe:
    """Minimal frappe module stand-in sufficient for stock_ledger_alerts."""

    def __init__(self, bin_doc, notification, bin_name, item_important_value):
        self.db = _FakeFrappeDB(bin_name, item_important_value)
        self._bin_doc = bin_doc
        self._notification = notification
        self.get_doc_calls = []

    def get_cached_doc(self, doctype, name):
        assert doctype == "Notification"
        return self._notification

    def get_doc(self, doctype, name):
        assert doctype == "Bin"
        self.get_doc_calls.append(name)
        return self._bin_doc


def _load_module_against_fake_frappe(fake_frappe):
    """Exec the real stock_ledger_alerts.py source with ``frappe`` stubbed.

    This loads the actual module source from disk (not a re-typed copy),
    substituting only the ``frappe`` dependency, so the test exercises the
    real ``send_important_item_low_stock_alert`` function body -- its
    LOW_STOCK_THRESHOLD comparison and important-item lookup ordering --
    rather than merely grepping the module text.
    """
    previous_frappe = sys.modules.get("frappe")
    sys.modules["frappe"] = fake_frappe
    try:
        spec = importlib.util.spec_from_file_location(
            "stock_ledger_alerts_under_test_%d" % id(fake_frappe), MODULE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous_frappe is not None:
            sys.modules["frappe"] = previous_frappe
        else:
            del sys.modules["frappe"]
    return module


LOW_STOCK_THRESHOLD_VALUE = 10


class TestQueueImportantItemLowStockAlertCollectsRealWarehouseFields(
    unittest.TestCase
):
    """Proves ``queue_important_item_low_stock_alert`` reads every real
    warehouse field shape off a submitted transaction's rows generically,
    without any Frappe installation required.
    """

    def test_collects_plain_warehouse_field(self):
        notification = _FakeNotification()
        bin_doc = _FakeBin("BIN-1", actual_qty=5)
        fake_frappe = _FakeFrappe(
            bin_doc, notification, bin_name=bin_doc.name, item_important_value=1
        )
        queued = []
        fake_frappe.db.after_commit = types.SimpleNamespace(
            add=lambda callback: queued.append(callback)
        )
        module = _load_module_against_fake_frappe(fake_frappe)

        doc = {"items": [{"item_code": "ITEM-A", "warehouse": "WH-A"}]}
        module.queue_important_item_low_stock_alert(doc)

        self.assertEqual(len(queued), 1)
        queued[0]()
        self.assertEqual(notification.sent_with, [bin_doc])

    def test_collects_stock_entry_source_and_target_warehouses(self):
        notification = _FakeNotification()
        bin_doc = _FakeBin("BIN-2", actual_qty=5)
        fake_frappe = _FakeFrappe(
            bin_doc, notification, bin_name=bin_doc.name, item_important_value=1
        )
        queued = []
        fake_frappe.db.after_commit = types.SimpleNamespace(
            add=lambda callback: queued.append(callback)
        )
        module = _load_module_against_fake_frappe(fake_frappe)

        doc = {
            "items": [
                {
                    "item_code": "ITEM-B",
                    "s_warehouse": "WH-SOURCE",
                    "t_warehouse": "WH-TARGET",
                }
            ]
        }
        module.queue_important_item_low_stock_alert(doc)

        # Both the source and target warehouse must be scheduled.
        self.assertEqual(len(queued), 2)

    def test_rows_without_item_code_are_skipped(self):
        notification = _FakeNotification()
        bin_doc = _FakeBin("BIN-3", actual_qty=5)
        fake_frappe = _FakeFrappe(
            bin_doc, notification, bin_name=bin_doc.name, item_important_value=1
        )
        queued = []
        fake_frappe.db.after_commit = types.SimpleNamespace(
            add=lambda callback: queued.append(callback)
        )
        module = _load_module_against_fake_frappe(fake_frappe)

        doc = {"items": [{"warehouse": "WH-A"}]}
        module.queue_important_item_low_stock_alert(doc)

        self.assertEqual(queued, [])


class TestSendImportantItemLowStockAlertFunctionBehaviour(unittest.TestCase):
    """Deterministic regression guard for the current correct behaviour.

    These cases load the real ``send_important_item_low_stock_alert``
    function source and execute it against a minimal, fully-controlled
    ``frappe`` stand-in (no SQLite, no network, no Frappe installation
    required) solely to pin down two concrete behaviours of the *current*
    implementation that a future refactor could silently break:

    1. When the final Bin ``actual_qty`` is at or above
       ``LOW_STOCK_THRESHOLD`` (10), the function must return without ever
       performing the ``Item.is_important_item`` lookup and without ever
       calling ``notification.send``.
    2. When the Bin quantity *is* below the threshold but the Item is not
       an important item, the function must still perform the
       ``Item.is_important_item`` lookup (proving the threshold check runs
       first and genuinely gates forward) but must return before reaching
       ``notification.send``.

    A positive control (important item, qty below threshold) proves the
    harness itself is wired correctly and that ``notification.send`` is
    reachable at all, so the two guard cases above are not trivially
    passing because ``send`` is unreachable for unrelated reasons.
    """

    def test_returns_without_item_lookup_when_qty_at_threshold(self):
        notification = _FakeNotification()
        bin_doc = _FakeBin("BIN-AT-THRESHOLD", actual_qty=LOW_STOCK_THRESHOLD_VALUE)
        fake_frappe = _FakeFrappe(
            bin_doc, notification, bin_name=bin_doc.name, item_important_value=1
        )
        module = _load_module_against_fake_frappe(fake_frappe)

        module.send_important_item_low_stock_alert("ITEM-IMPORTANT", "WH-1")

        self.assertEqual(
            fake_frappe.db.item_lookup_calls,
            [],
            "actual_qty == LOW_STOCK_THRESHOLD must return before the "
            "Item.is_important_item lookup is ever performed",
        )
        self.assertEqual(notification.sent_with, [])

    def test_returns_without_item_lookup_when_qty_above_threshold(self):
        notification = _FakeNotification()
        bin_doc = _FakeBin("BIN-ABOVE-THRESHOLD", actual_qty=15)
        fake_frappe = _FakeFrappe(
            bin_doc, notification, bin_name=bin_doc.name, item_important_value=1
        )
        module = _load_module_against_fake_frappe(fake_frappe)

        module.send_important_item_low_stock_alert("ITEM-IMPORTANT", "WH-1")

        self.assertEqual(
            fake_frappe.db.item_lookup_calls,
            [],
            "actual_qty >= LOW_STOCK_THRESHOLD must return before the "
            "Item.is_important_item lookup is ever performed",
        )
        self.assertEqual(notification.sent_with, [])

    def test_returns_for_unimportant_item_before_notification_send(self):
        notification = _FakeNotification()
        bin_doc = _FakeBin("BIN-BELOW-THRESHOLD", actual_qty=5)
        fake_frappe = _FakeFrappe(
            bin_doc, notification, bin_name=bin_doc.name, item_important_value=0
        )
        module = _load_module_against_fake_frappe(fake_frappe)

        module.send_important_item_low_stock_alert("ITEM-UNIMPORTANT", "WH-1")

        self.assertEqual(
            fake_frappe.db.item_lookup_calls,
            [("ITEM-UNIMPORTANT", "is_important_item")],
            "the LOW_STOCK_THRESHOLD comparison must have already passed, "
            "reaching the Item.is_important_item lookup",
        )
        self.assertEqual(
            notification.sent_with,
            [],
            "an unimportant item must never reach notification.send(bin_doc)",
        )

    def test_sends_when_important_item_and_qty_below_threshold(self):
        # Positive control: proves notification.send is reachable at all
        # through this exact code path, so the two guard cases above are
        # not passing merely because send() is unreachable for unrelated
        # reasons.
        notification = _FakeNotification()
        bin_doc = _FakeBin("BIN-POSITIVE-CONTROL", actual_qty=5)
        fake_frappe = _FakeFrappe(
            bin_doc, notification, bin_name=bin_doc.name, item_important_value=1
        )
        module = _load_module_against_fake_frappe(fake_frappe)

        module.send_important_item_low_stock_alert("ITEM-IMPORTANT", "WH-1")

        self.assertEqual(
            fake_frappe.db.item_lookup_calls,
            [("ITEM-IMPORTANT", "is_important_item")],
        )
        self.assertEqual(notification.sent_with, [bin_doc])


if __name__ == "__main__":
    unittest.main()
