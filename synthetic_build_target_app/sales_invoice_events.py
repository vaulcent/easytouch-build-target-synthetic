"""Sales Invoice document-event automation.

Requirement: every time a submitted Sales Invoice is created, automatically
create a Project for that invoice using the customer name and invoice
number.

This module is registered against the Sales Invoice ``on_submit`` hook in
``hooks.py``. Frappe is imported lazily inside each function so this module
stays importable (for static/unit checks) even when Frappe is not installed
in the local sandbox; the real app only ever calls these functions from
inside a live Frappe/ERPNext request or ``bench execute`` context.
"""


def build_project_name(sales_invoice):
    """Deterministically derive the descriptive Project label for a Sales
    Invoice (customer + invoice number).

    This value is always written to the Project's ``project_name`` field.
    It is NOT assumed to also become the Project document's primary
    ``name``: ERPNext's Project doctype naming strategy (``autoname``) is
    site/version dependent (it may be field-based, prompt-based, a naming
    series, or a hash), and forcing ``doc.name`` manually is unreliable
    across configurations -- Frappe's own ``set_new_name`` resets an
    explicitly assigned ``name`` back to ``None`` for any non-"prompt"
    autoname strategy before deriving the real name. So idempotency and
    lookups below are always done by querying the ``project_name`` field
    value, never by assuming it equals the Project's primary key.
    """
    customer_label = getattr(sales_invoice, "customer_name", None) or sales_invoice.customer
    return "{0} - {1}".format(customer_label, sales_invoice.name)


def create_project_from_sales_invoice(doc, method=None):
    """Idempotently create a Project for every submitted Sales Invoice.

    Registered against the Sales Invoice ``on_submit`` hook. Only fires the
    creation logic for submitted (docstatus == 1) invoices, so draft
    invoices never create a Project. Safe to call more than once for the
    same invoice (e.g. on event retry): it looks up an existing Project by
    its deterministic ``project_name`` field value before inserting a new
    one, so repeated on_submit events for the same invoice never create a
    duplicate Project.

    Returns the created/looked-up Project's actual document name (its
    primary key), which may or may not equal ``build_project_name(doc)``
    depending on the Project doctype's autoname configuration.
    """
    import frappe

    if doc.docstatus != 1:
        return None

    project_name = build_project_name(doc)

    existing_project = frappe.db.get_value(
        "Project", {"project_name": project_name}, "name"
    )
    if existing_project:
        return existing_project

    project = frappe.new_doc("Project")
    project.project_name = project_name
    project.company = doc.company
    try:
        project.customer = doc.customer
    except Exception:
        pass
    project.insert(ignore_permissions=True)
    return project.name
