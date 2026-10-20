"""Dependency-free unit tests for the low-stock alert gating/routing logic.

These exercise the pure Python helpers in
``synthetic_build_target_app.stock_alerts`` directly with plain Python
stand-ins for Frappe documents, so they run in the local sandbox where
Frappe is not installed. They are NOT ERP behavior evidence by
themselves; the authoritative, Frappe-backed proof of the real
automation lives in tests/test_low_stock_alert_erp_behavior.py.
"""

import unittest

from synthetic_build_target_app import stock_alerts
from synthetic_build_target_app.hooks import doc_events


class _FakeDoc:
    """Minimal stand-in exposing the subset of the Frappe document API
    (``doctype``, ``.get``) that stock_alerts.doc_moves_stock /
    affected_item_codes actually rely on."""

    def __init__(self, doctype, name="FAKE-0001", update_stock=None, items=None):
        self.doctype = doctype
        self.name = name
        self._data = {"update_stock": update_stock, "items": items or []}

    def get(self, key, default=None):
        return self._data.get(key, default)


class DocMovesStockTests(unittest.TestCase):
    def test_all_six_required_sources_are_recognised(self):
        self.assertEqual(
            stock_alerts.STOCK_MOVING_DOCTYPES,
            {
                "Sales Invoice",
                "Delivery Note",
                "Purchase Receipt",
                "Purchase Invoice",
                "Stock Entry",
                "Stock Reconciliation",
            },
        )

    def test_unconditional_sources_always_move_stock(self):
        for doctype in ("Delivery Note", "Purchase Receipt", "Stock Entry", "Stock Reconciliation"):
            with self.subTest(doctype=doctype):
                self.assertTrue(stock_alerts.doc_moves_stock(_FakeDoc(doctype)))

    def test_sales_invoice_only_moves_stock_when_update_stock_enabled(self):
        self.assertFalse(
            stock_alerts.doc_moves_stock(_FakeDoc("Sales Invoice", update_stock=0))
        )
        self.assertFalse(
            stock_alerts.doc_moves_stock(_FakeDoc("Sales Invoice", update_stock=None))
        )
        self.assertTrue(
            stock_alerts.doc_moves_stock(_FakeDoc("Sales Invoice", update_stock=1))
        )

    def test_purchase_invoice_only_moves_stock_when_update_stock_enabled(self):
        self.assertFalse(
            stock_alerts.doc_moves_stock(_FakeDoc("Purchase Invoice", update_stock=0))
        )
        self.assertTrue(
            stock_alerts.doc_moves_stock(_FakeDoc("Purchase Invoice", update_stock=1))
        )

    def test_unrelated_doctype_never_moves_stock(self):
        self.assertFalse(stock_alerts.doc_moves_stock(_FakeDoc("Issue")))


class AffectedItemCodesTests(unittest.TestCase):
    def test_collects_distinct_item_codes_from_rows(self):
        doc = _FakeDoc(
            "Stock Entry",
            items=[
                {"item_code": "ITEM-B"},
                {"item_code": "ITEM-A"},
                {"item_code": "ITEM-A"},
                {},
            ],
        )
        self.assertEqual(stock_alerts.affected_item_codes(doc), ["ITEM-A", "ITEM-B"])

    def test_no_items_returns_empty_list(self):
        self.assertEqual(stock_alerts.affected_item_codes(_FakeDoc("Stock Entry")), [])


class HooksWiringTests(unittest.TestCase):
    """Confirm hooks.py registers the real low-stock handler on both
    on_submit and on_cancel for every stock-moving source, since either
    direction can cross the threshold.

    Sales Invoice already carries another, already-landed on_submit
    handler (Sales Invoice -> Project automation), so its on_submit entry
    is a list containing both handlers rather than a bare string; every
    other stock-moving doctype's handlers remain plain strings.
    """

    def test_every_stock_moving_doctype_has_submit_and_cancel_hooks(self):
        handler = "synthetic_build_target_app.stock_alerts.queue_low_stock_check"
        for doctype in stock_alerts.STOCK_MOVING_DOCTYPES:
            with self.subTest(doctype=doctype):
                self.assertIn(doctype, doc_events)

                on_submit = doc_events[doctype].get("on_submit")
                if isinstance(on_submit, (list, tuple)):
                    self.assertIn(handler, on_submit)
                else:
                    self.assertEqual(on_submit, handler)

                on_cancel = doc_events[doctype].get("on_cancel")
                if isinstance(on_cancel, (list, tuple)):
                    self.assertIn(handler, on_cancel)
                else:
                    self.assertEqual(on_cancel, handler)

    def test_sales_invoice_keeps_the_existing_project_automation_hook(self):
        project_handler = (
            "synthetic_build_target_app.sales_invoice_project."
            "create_project_for_submitted_sales_invoice"
        )
        on_submit = doc_events["Sales Invoice"].get("on_submit")
        self.assertIn(project_handler, on_submit)


if __name__ == "__main__":
    unittest.main()
