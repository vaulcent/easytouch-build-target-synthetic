"""Low stock alert automation.

Requirement: when stock for an item marked "important" drops below a
threshold, the Purchase Manager must automatically get an alert.

Design notes
------------
Sales Invoice, Delivery Note, Purchase Receipt, Purchase Invoice (only
when ``update_stock`` is enabled), Stock Entry and Stock Reconciliation
are the only standard documents whose submission/cancellation lifecycle
changes Bin.actual_qty. Each of them is registered in hooks.py for both
``on_submit`` and ``on_cancel``, because stock can cross the low-stock
threshold in either direction.

Stock Ledger Entry / Bin rows are written internally by these
controllers via ``db_insert`` and do not reliably emit ordinary DocType
events, so this module hooks the real originating transaction instead
and only reads the Bin after that transaction's database changes have
committed.

The check is scheduled with ``frappe.db.after_commit.add(...)``, a
plain in-process callback that Frappe itself invokes synchronously
*during* the ``frappe.db.commit()`` call that follows the originating
document's submit/cancel -- it does not depend on an RQ background
queue worker (the disposable validation lanes do not run one), and it
guarantees the Bin is only inspected once this transaction's own
database changes have actually committed rather than an in-transaction
value that could later roll back.

Notification Log creation itself still goes through Frappe's own,
standard System Notification path
(``notification_log.enqueue_create_notification``), which internally
honours ``frappe.flags.in_test`` to deliver synchronously when a test
sets that flag for the duration of the triggering submit + commit.

``frappe`` is imported lazily inside the functions that actually need
it so that the pure routing/gating logic below (``doc_moves_stock`` and
``affected_item_codes``) can be unit tested with plain Python objects
in environments where Frappe is not installed.
"""

LOW_STOCK_THRESHOLD = 10

#: Doctypes whose submit/cancel lifecycle can move a Bin's actual_qty.
STOCK_MOVING_DOCTYPES = {
    "Sales Invoice",
    "Delivery Note",
    "Purchase Receipt",
    "Purchase Invoice",
    "Stock Entry",
    "Stock Reconciliation",
}

#: Doctypes that only move stock conditionally, via update_stock.
CONDITIONAL_UPDATE_STOCK_DOCTYPES = {"Sales Invoice", "Purchase Invoice"}


def doc_moves_stock(doc) -> bool:
    """Return True only when this particular document actually moves stock.

    Sales Invoice and Purchase Invoice only touch the Bin when
    ``update_stock`` is checked; without it they must not queue a
    low-stock check (that would be a false alert).
    """
    if doc.doctype not in STOCK_MOVING_DOCTYPES:
        return False
    if doc.doctype in CONDITIONAL_UPDATE_STOCK_DOCTYPES:
        return bool(doc.get("update_stock"))
    return True


def affected_item_codes(doc):
    """Collect the distinct item codes touched by this document's rows."""
    item_codes = set()
    for row in doc.get("items", []) or []:
        item_code = row.get("item_code")
        if item_code:
            item_codes.add(item_code)
    return sorted(item_codes)


def queue_low_stock_check(doc, method=None):
    """doc_event hook for on_submit / on_cancel of stock-moving documents.

    Registers ``run_low_stock_check`` as an in-process
    ``frappe.db.after_commit`` callback so the Bin is only read once
    this transaction's own database changes have committed, and so the
    check runs synchronously (no background queue worker required) the
    moment ``frappe.db.commit()`` is actually invoked for this
    transaction.
    """
    if not doc_moves_stock(doc):
        return

    item_codes = affected_item_codes(doc)
    if not item_codes:
        return

    import frappe

    frappe.db.after_commit.add(lambda: run_low_stock_check(item_codes))


def run_low_stock_check(item_codes):
    """Runs (synchronously, after commit) for each affected item code:
    alert Purchase Managers if it is marked important and its current
    total stock is below threshold."""
    for item_code in item_codes:
        check_item_stock_level(item_code)


def check_item_stock_level(item_code):
    import frappe
    from frappe import _

    is_important = frappe.db.get_value("Item", item_code, "important_item")
    if not is_important:
        return

    total_qty = frappe.db.sql(
        "select sum(actual_qty) from `tabBin` where item_code=%s",
        item_code,
    )[0][0] or 0

    if total_qty >= LOW_STOCK_THRESHOLD:
        return

    recipients = purchase_manager_recipients()
    if not recipients:
        return

    notification_doc = {
        "type": "Alert",
        "document_type": "Item",
        "document_name": item_code,
        "subject": _("Low stock alert: {0} has only {1} in stock").format(
            item_code, total_qty
        ),
        "email_content": _(
            "Important item {0} has fallen below the low-stock threshold of "
            "{1}. Current total stock: {2}."
        ).format(item_code, LOW_STOCK_THRESHOLD, total_qty),
    }

    from frappe.desk.doctype.notification_log.notification_log import (
        enqueue_create_notification,
    )

    enqueue_create_notification(recipients, notification_doc)


def purchase_manager_recipients():
    """Enabled Users holding the Purchase Manager role."""
    import frappe

    user_names = frappe.get_all(
        "Has Role",
        filters={"role": "Purchase Manager", "parenttype": "User"},
        pluck="parent",
    )
    if not user_names:
        return []
    return frappe.get_all(
        "User",
        filters={"name": ["in", user_names], "enabled": 1},
        pluck="name",
    )
