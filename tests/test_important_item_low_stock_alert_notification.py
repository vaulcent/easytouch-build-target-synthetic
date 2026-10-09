import json
import os
import unittest

NOTIFICATION_FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "notification.json",
)

HOOKS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "hooks.py",
)


class TestImportantItemLowStockAlertNotification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(NOTIFICATION_FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _alert_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Notification"
            and entry.get("name") == "Important Item Low Stock Alert"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_alert_exists_exactly_once(self):
        entries = self._alert_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Important Item Low Stock Alert' Notification "
            "fixture (idempotent - no duplicates).",
        )

    def test_alert_targets_bin_document_type(self):
        entry = self._alert_entries()[0]
        self.assertEqual(entry["document_type"], "Bin")
        self.assertEqual(entry.get("enabled"), 1)
        self.assertEqual(entry.get("channel"), "Email")

    def test_alert_uses_custom_event_not_wired_to_ordinary_bin_saves(self):
        # "Custom" is not auto-triggered by core Bin save/value-change doc
        # events, so this Notification cannot separately fire for ordinary
        # Bin saves; it is only ever dispatched explicitly by the
        # stock_ledger_alerts hook calling notification.send(bin_doc).
        entry = self._alert_entries()[0]
        self.assertEqual(entry["event"], "Custom")
        self.assertNotIn("value_changed", entry)

    def test_alert_condition_is_limited_to_valid_bin_fields(self):
        # Real ERPNext v16 metadata validation rejects a condition
        # referencing doc.is_important_item on Bin (no such field), and
        # frappe.db access from a Notification's safe_eval'd condition is
        # forbidden. The stored condition must therefore reference only a
        # real Bin field.
        entry = self._alert_entries()[0]
        condition = entry["condition"]
        self.assertIn("doc.actual_qty < 10", condition)
        self.assertNotIn("is_important_item", condition)
        self.assertNotIn("frappe.db", condition)

    def test_alert_recipient_is_purchase_manager_role(self):
        entry = self._alert_entries()[0]
        recipients = entry.get("recipients", [])
        self.assertEqual(len(recipients), 1)
        self.assertEqual(recipients[0].get("receiver_by_role"), "Purchase Manager")

    def test_no_duplicate_notification_names(self):
        seen = set()
        for entry in self.fixtures:
            name = entry.get("name")
            self.assertNotIn(name, seen, f"Duplicate Notification fixture: {name}")
            seen.add(name)

    def test_hooks_register_notification_fixture(self):
        with open(HOOKS_PATH, "r", encoding="utf-8") as handle:
            hooks_content = handle.read()
        self.assertIn("Notification", hooks_content)
        self.assertIn("Custom Field", hooks_content)


if __name__ == "__main__":
    unittest.main()
