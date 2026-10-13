"""Idempotent fixture integration used after site migrations."""

from __future__ import annotations

import json
from pathlib import Path

import frappe

_APP_ROOT = Path(__file__).resolve().parents[1]


def ensure_important_item_notification() -> None:
    fixture = _APP_ROOT / "fixtures" / "notification.json"
    record = json.loads(fixture.read_text(encoding="utf-8"))[0]
    name = record["name"]
    if frappe.db.exists("Notification", name):
        document = frappe.get_doc("Notification", name)
        document.update(record)
        document.save(ignore_permissions=True)
    else:
        frappe.get_doc(record).insert(ignore_permissions=True)


#: Canonical name of the standard Query Report this module keeps in sync.
SALESPERSON_SALES_SUMMARY_REPORT_NAME = "Salesperson Sales Summary"

_SALESPERSON_SALES_SUMMARY_SQL_PATH = (
    _APP_ROOT
    / "synthetic_build_target_app"
    / "report"
    / "salesperson_sales_summary"
    / "salesperson_sales_summary.sql"
)


def ensure_salesperson_sales_summary_report_query() -> None:
    """Keep the installed "Salesperson Sales Summary" Report's ``query``
    database field in sync with the shipped, read-only
    ``salesperson_sales_summary.sql`` file.

    The on-disk Report JSON fixture deliberately does not embed the SQL
    (the adjacent .sql file is the single, reviewable source of truth for
    the query), so ``frappe.desk.query_report.run`` -- which reads the
    ``query`` field straight off the real database Report record -- needs
    that field explicitly backfilled from the file. This idempotently
    (re)loads the file and only writes when the stored value differs, so
    re-running it on every migrate is always a safe no-op once in sync.
    """
    query = _SALESPERSON_SALES_SUMMARY_SQL_PATH.read_text(encoding="utf-8")

    if not frappe.db.exists("Report", SALESPERSON_SALES_SUMMARY_REPORT_NAME):
        frappe.reload_doc(
            "synthetic_build_target_app", "report", "salesperson_sales_summary"
        )

    if not frappe.db.exists("Report", SALESPERSON_SALES_SUMMARY_REPORT_NAME):
        # Standard report sync did not create the document (for example,
        # the app/module is not yet registered on this site); nothing
        # further can be done until it exists.
        return

    current_query = frappe.db.get_value(
        "Report", SALESPERSON_SALES_SUMMARY_REPORT_NAME, "query"
    )
    if current_query == query:
        return

    report = frappe.get_doc("Report", SALESPERSON_SALES_SUMMARY_REPORT_NAME)
    report.query = query
    report.save(ignore_permissions=True)
