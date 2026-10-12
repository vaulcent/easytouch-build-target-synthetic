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


#: DocType the "Sales Invoice Discount Approval" Workflow (see
#: fixtures/workflow.json) governs.
DISCOUNT_APPROVAL_WORKFLOW_DOCTYPE = "Sales Invoice"

#: Exact Sales Invoice permissions each workflow role needs to actually
#: execute its transitions, derived from the workflow's state/transition
#: matrix:
#:   - "Sales User" must read/write/create a Draft Sales Invoice, and
#:     needs live *submit* permission to execute the Draft -> Approved
#:     transition itself when additional_discount_percentage <= 10 (that
#:     transition's next state has doc_status=1, i.e. a real submit).
#:   - "Sales Manager" must read/write the Pending Manager Approval state
#:     (allow_edit), and needs live *submit* permission to execute the
#:     Pending Manager Approval -> Approved transition when
#:     additional_discount_percentage > 10 (also doc_status=1).
#: Neither role needs cancel/amend for this workflow: every transition's
#: next state is either doc_status=0 (an ordinary save) or doc_status=1
#: via submit, so only read/write/create/submit are granted -- never a
#: speculative cancel/amend grant.
DISCOUNT_APPROVAL_PERMISSION_GRANTS = {
    "Sales User": {"read": 1, "write": 1, "create": 1, "submit": 1},
    "Sales Manager": {"read": 1, "write": 1, "create": 1, "submit": 1},
}


def _ensure_custom_doc_perms(doctype: str, grants: dict) -> None:
    """Idempotently grant each ``role -> {permission: 1}`` mapping in
    ``grants`` to ``doctype`` via Custom DocPerm.

    Calls ``frappe.permissions.setup_custom_perms`` first so the standard
    DocPerm table is copied into Custom DocPerm (preserving every
    existing row) before this updates/inserts only the exact role rows
    required -- the whole permission table is never replaced. Safe to run
    on every migrate: once a role already has every required bit set,
    this is a no-op for that role.
    """
    frappe.permissions.setup_custom_perms(doctype)

    for role, required in grants.items():
        existing = frappe.get_all(
            "Custom DocPerm",
            filters={"parent": doctype, "role": role, "permlevel": 0},
            fields=["name"],
            limit=1,
        )
        if existing:
            doc = frappe.get_doc("Custom DocPerm", existing[0]["name"])
            changed = False
            for fieldname, value in required.items():
                if not doc.get(fieldname):
                    doc.set(fieldname, value)
                    changed = True
            if changed:
                doc.save(ignore_permissions=True)
        else:
            doc = frappe.get_doc(
                {
                    "doctype": "Custom DocPerm",
                    "parent": doctype,
                    "parenttype": "DocType",
                    "parentfield": "permissions",
                    "role": role,
                    "permlevel": 0,
                    **required,
                }
            )
            doc.insert(ignore_permissions=True)

    frappe.clear_cache(doctype=doctype)


def ensure_discount_approval_workflow_permissions() -> None:
    """Idempotently grant the "Sales Invoice Discount Approval" Workflow's
    two roles (Sales User, Sales Manager) the exact Sales Invoice
    read/write/create/submit permissions their transitions require (see
    ``DISCOUNT_APPROVAL_PERMISSION_GRANTS`` above for the matrix this is
    derived from).
    """
    _ensure_custom_doc_perms(
        DISCOUNT_APPROVAL_WORKFLOW_DOCTYPE, DISCOUNT_APPROVAL_PERMISSION_GRANTS
    )


#: DocType the "Sales Order Finance Approval" Workflow (see
#: fixtures/workflow.json) governs.
SALES_ORDER_FINANCE_APPROVAL_WORKFLOW_DOCTYPE = "Sales Order"

#: Exact Sales Order permissions each workflow role needs to actually
#: execute its transitions, derived from this workflow's state/transition
#: matrix:
#:
#:   state                       doc_status  allow_edit
#:   Draft                       0           Sales User
#:   Pending Finance Approval    0           Finance Approval
#:   Approved                    1           Finance Approval
#:
#:   transition                                            allowed role     condition               underlying live permission
#:   Draft -> Approved          (action "Submit")           Sales User       grand_total <= 5000     SUBMIT (next doc_status=1)
#:   Draft -> Pending Fin.Appr. (action "Send for Finance Approval") Sales User grand_total > 5000   WRITE (next doc_status=0, ordinary save)
#:   Pending Fin.Appr -> Approved (action "Approve")        Finance Approval grand_total > 5000      SUBMIT (next doc_status=1)
#:
#: - "Sales User" must read/write/create a Draft Sales Order, and needs
#:   live *submit* permission to execute the Draft -> Approved transition
#:   itself when grand_total <= 5000.
#: - "Finance Approval" must read/write the Pending Finance Approval
#:   state (allow_edit), and needs live *submit* permission to execute
#:   the Pending Finance Approval -> Approved transition when
#:   grand_total > 5000. It never creates the order itself, so create is
#:   not granted.
#: Neither role needs cancel/amend for this workflow: every transition's
#: next state is either doc_status=0 (an ordinary save) or doc_status=1
#: via submit, so only read/write/(create)/submit are granted -- never a
#: speculative cancel/amend grant.
SALES_ORDER_FINANCE_APPROVAL_PERMISSION_GRANTS = {
    "Sales User": {"read": 1, "write": 1, "create": 1, "submit": 1},
    "Finance Approval": {"read": 1, "write": 1, "submit": 1},
}


def ensure_sales_order_finance_approval_workflow_permissions() -> None:
    """Idempotently grant the "Sales Order Finance Approval" Workflow's
    two roles (Sales User, Finance Approval) the exact Sales Order
    read/write/(create)/submit permissions their transitions require
    (see ``SALES_ORDER_FINANCE_APPROVAL_PERMISSION_GRANTS`` above for the
    matrix this is derived from).
    """
    _ensure_custom_doc_perms(
        SALES_ORDER_FINANCE_APPROVAL_WORKFLOW_DOCTYPE,
        SALES_ORDER_FINANCE_APPROVAL_PERMISSION_GRANTS,
    )
