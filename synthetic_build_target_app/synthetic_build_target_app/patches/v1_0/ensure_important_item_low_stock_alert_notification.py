"""Idempotent patch: insert the Important Item Low Stock Alert Notification
if (and only if) it does not already exist on this site.

This patch is the sole patches.txt-registered entry point that guarantees
the pre-existing "Important Item Low Stock Alert" Notification document
(reused by synthetic_build_target_app.synthetic_build_target_app.
stock_ledger_alerts.send_important_item_low_stock_alert) is present on a
site even if it was never installed via the app's fixtures/after_migrate
path. It is deliberately insertion-only: if the Notification already
exists, this patch takes no action at all (no update, no overwrite),
so re-running it on every migrate is always a safe no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe

#: Name of the Notification document this patch idempotently ensures
#: exists. Kept as a plain constant so the explicit existence guard below
#: is unambiguous about exactly which document it checks for.
NOTIFICATION_NAME = "Important Item Low Stock Alert"

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "notification.json"
)


def execute() -> None:
    """Insert the Notification fixture record only if it is missing.

    Explicit existence guard: if ``Notification`` named
    ``NOTIFICATION_NAME`` already exists on this site, return immediately
    without touching it. Only on the missing path is the record read from
    the shipped fixture and inserted.
    """
    if frappe.db.exists("Notification", NOTIFICATION_NAME):
        return

    record = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))[0]
    frappe.get_doc(record).insert(ignore_permissions=True)
