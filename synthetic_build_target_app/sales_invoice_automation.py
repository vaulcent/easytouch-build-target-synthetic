"""Server-side automation: create a Project for every submitted Sales Invoice.

Registered in hooks.py as an ``on_submit`` doc_event for Sales Invoice.

The created Project's ``project_name`` field is set deterministically from
the invoice's customer and invoice number. Project's own autoname
behaviour (whether its primary ``name`` literally equals ``project_name``
or is generated some other way, e.g. a naming series) is an internal
ERPNext implementation detail that this handler must not assume. All
lookups -- both the idempotency check below and any caller that needs to
find the Project for an invoice -- must therefore query by the
``project_name`` field value, never by treating that deterministic string
as if it were the Project's document name.

Because the handler always checks for an existing Project with that
``project_name`` before inserting, re-running it for the same invoice --
for example because the submit event is retried -- is a no-op and never
creates a duplicate Project.
"""

import frappe


def project_name_for_invoice(invoice):
    """Build the deterministic Project name for a Sales Invoice.

    Uses the invoice's customer name (falling back to the customer code)
    and the invoice number, per the requirement.
    """
    customer_label = getattr(invoice, "customer_name", None) or invoice.customer
    return f"{customer_label} - {invoice.name}"


def get_project_for_invoice(invoice):
    """Return the existing Project docname linked to this invoice, if any.

    Looks up by the ``project_name`` field rather than assuming it equals
    the Project's primary ``name``.
    """
    name = project_name_for_invoice(invoice)
    return frappe.db.get_value("Project", {"project_name": name}, "name")


def create_project_on_submit(doc, method=None):
    """Create exactly one Project for this submitted Sales Invoice.

    Idempotent: if a Project whose ``project_name`` field already matches
    the deterministic name exists (because this handler already ran for
    this invoice, e.g. an on_submit event retry), nothing further happens.
    """
    if doc.doctype != "Sales Invoice" or doc.docstatus != 1:
        return

    name = project_name_for_invoice(doc)

    if frappe.db.exists("Project", {"project_name": name}):
        return

    project = frappe.get_doc(
        {
            "doctype": "Project",
            "project_name": name,
            "customer": doc.customer,
            "company": doc.company,
        }
    )
    project.insert(ignore_permissions=True)
