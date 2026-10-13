"""Idempotent fixture integration used after site migrations."""

from __future__ import annotations

import json
from pathlib import Path

import frappe


def ensure_important_item_notification() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "notification.json"
    record = json.loads(fixture.read_text(encoding="utf-8"))[0]
    name = record["name"]
    if frappe.db.exists("Notification", name):
        document = frappe.get_doc("Notification", name)
        document.update(record)
        document.save(ignore_permissions=True)
    else:
        frappe.get_doc(record).insert(ignore_permissions=True)
