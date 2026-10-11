"""Sales Invoice submission hook: auto-create a linked Project.

Requirement: "Every time a submitted Sales Invoice is created,
automatically create a Project for that invoice using the customer name
and invoice number."

Wired to the real ``on_submit`` document-lifecycle event of ``Sales
Invoice`` in hooks.py (alongside the existing low-stock-alert hook -- both
run, via a list of handlers for the same event), so this fires on every
genuine Sales Invoice submission a user actually performs.

Idempotency: the created Project is linked back to its originating Sales
Invoice via the real ``sales_invoice`` Custom Field on Project (see
fixtures/custom_field.json). Before creating a new Project this module
checks whether one already exists for this exact Sales Invoice name via
that link field and, if so, does nothing -- so calling this hook more than
once for the same invoice (e.g. the hook running again for any reason)
never creates duplicate Projects.
"""

from __future__ import annotations

import frappe


def create_project_for_submitted_sales_invoice(doc, method=None) -> None:
    """Create a Project for ``doc`` (a just-submitted Sales Invoice).

    ``doc`` is the real submitted Sales Invoice passed in by Frappe's
    ``on_submit`` document-event dispatch. Idempotently skips creation if
    a Project already exists for this exact invoice name.
    """
    invoice_name = doc.get("name")

    existing = frappe.db.get_value(
        "Project", {"sales_invoice": invoice_name}, "name"
    )
    if existing:
        return existing

    customer_name = doc.get("customer_name") or doc.get("customer") or ""
    project_name = "{0} - {1}".format(customer_name, invoice_name)

    project = frappe.get_doc(
        {
            "doctype": "Project",
            "project_name": project_name,
            "sales_invoice": invoice_name,
            "customer": doc.get("customer"),
            "company": doc.get("company"),
        }
    )
    project.insert(ignore_permissions=True)
    return project.name
