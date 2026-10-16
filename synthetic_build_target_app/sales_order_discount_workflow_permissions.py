"""Deployable app lifecycle permission setup for the Sales Order
discount-approval Workflow (see the "Workflow" fixture in
synthetic_build_target_app/fixtures/workflow.json and its registration in
hooks.py).

Requirement: salespeople must not be able to approve big discounts
themselves. If a Sales Order's additional_discount_percentage is more
than 10, it must go to a Sales Manager for approval instead of being
submittable directly by the salesperson.

Permission matrix derived from that Workflow's own states/transitions:

* Draft (docstatus 0, allow_edit "Sales User")
    -> "Submit" -> Approved (docstatus 1), allowed role "Sales User",
       condition additional_discount_percentage <= 10.
       This is a 0 -> 1 transition: it performs a real ERPNext submit, so
       "Sales User" needs live read/write/create/submit permission on
       Sales Order.
    -> "Send for Approval" -> Pending Manager Approval (docstatus 0),
       allowed role "Sales User", condition
       additional_discount_percentage > 10.
       This is a 0 -> 0 transition (an ordinary save): it only needs
       read/write permission, already covered by the submit grant above.
* Pending Manager Approval (docstatus 0, allow_edit "Sales Manager")
    -> "Approve" -> Approved (docstatus 1), allowed role "Sales Manager",
       allow_self_approval = 0.
       This is also a 0 -> 1 transition: it performs a real ERPNext
       submit, so "Sales Manager" needs live read/write/create/submit
       permission on Sales Order.

This module only ever *adds* the exact read/write/create/submit grant the
matrix above demonstrates is missing -- never speculative cancel/amend
rights, and never by replacing the DocType's whole permission table. It
is idempotent: safe to run on every migrate, and a no-op once both roles
already carry the required rights (which is the common case, since
ERPNext ships both "Sales User" and "Sales Manager" with submit rights on
Sales Order out of the box).
"""

DOCTYPE = "Sales Order"

# Exact, minimal grant required by the transition matrix above. Deny
# everything else (delete/cancel/amend) that the requirement did not ask
# for.
REQUIRED_PERMISSIONS = {
    "Sales User": {"read": 1, "write": 1, "create": 1, "submit": 1},
    "Sales Manager": {"read": 1, "write": 1, "create": 1, "submit": 1},
}


def ensure_discount_approval_permissions():
    """Idempotently ensure "Sales User" and "Sales Manager" both hold the
    minimal read/write/create/submit permission on Sales Order that the
    discount-approval Workflow's transitions require.

    Uses Frappe's own Custom DocPerm metadata helpers so the standard
    permission table is preserved (setup_custom_perms copies it on first
    use) and only the exact missing role/permlevel grant is added or
    repaired -- never a wholesale replacement of the DocType's permission
    table.
    """
    import frappe
    from frappe.permissions import (
        add_permission,
        setup_custom_perms,
        update_permission_property,
    )

    setup_custom_perms(DOCTYPE)

    for role, required in REQUIRED_PERMISSIONS.items():
        rows = frappe.get_all(
            "Custom DocPerm",
            filters={"parent": DOCTYPE, "role": role, "permlevel": 0},
            fields=["name"] + list(required.keys()),
        )
        if not rows:
            add_permission(DOCTYPE, role, 0)
            rows = frappe.get_all(
                "Custom DocPerm",
                filters={"parent": DOCTYPE, "role": role, "permlevel": 0},
                fields=["name"] + list(required.keys()),
            )

        for row in rows:
            for field, value in required.items():
                if not row.get(field):
                    update_permission_property(DOCTYPE, role, 0, field, value)

    frappe.clear_cache(doctype=DOCTYPE)
