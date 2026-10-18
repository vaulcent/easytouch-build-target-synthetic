"""Server-side automation: create a Project for every submitted Sales Invoice.

Registered against the Sales Invoice DocType's real ``on_submit`` lifecycle
hook (see ``hooks.py`` -> ``doc_events``). The handler is idempotent: if the
same submitted-invoice event is delivered more than once (for example an
event-queue retry, or a caller re-invoking the hook), no duplicate Project
is created for that invoice.
"""

import frappe


def create_project_from_sales_invoice(doc, method=None):
    """Create exactly one Project for this submitted Sales Invoice.

    The created Project is linked back to its source Sales Invoice through
    the ``synthetic_sales_invoice`` custom field. That link field is the
    idempotency key used to detect retries of the same submit event.
    """
    if not doc.customer or not doc.name:
        return

    # Idempotency guard: if a Project already points at this Sales Invoice,
    # do nothing. This protects against duplicate on_submit event delivery
    # (queue retries, re-running the hook, etc.).
    if frappe.db.exists("Project", {"synthetic_sales_invoice": doc.name}):
        return

    customer_label = (
        frappe.db.get_value("Customer", doc.customer, "customer_name") or doc.customer
    )
    project_name = f"{customer_label} - {doc.name}"

    project = frappe.get_doc(
        {
            "doctype": "Project",
            "project_name": project_name,
            "customer": doc.customer,
            "company": doc.company,
            "synthetic_sales_invoice": doc.name,
        }
    )
    project.insert(ignore_permissions=True)
    return project.name
