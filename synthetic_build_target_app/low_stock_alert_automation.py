"""Server-side automation: alert the Purchase Manager when stock for any
item marked ``important_item`` (Item.important_item, the "Important Item"
Custom Field) drops below ``LOW_STOCK_THRESHOLD`` in any warehouse.

Registered in hooks.py as ``on_submit``/``on_cancel`` doc_events for every
real source transaction whose lifecycle changes Bin quantities:

* Sales Invoice   (only when ``update_stock`` is enabled)
* Delivery Note
* Purchase Receipt
* Purchase Invoice (only when ``update_stock`` is enabled)
* Stock Entry
* Stock Reconciliation

Both directions (submit and cancel) are hooked because either can cross the
threshold: a cancelled issue restores quantity, a cancelled receipt removes
it again.

Stock Ledger Entry and Bin writes do not reliably emit ordinary document
lifecycle events of their own, so this module hooks the originating
transaction instead and reads the Bin only once the enclosing database
transaction has actually committed -- registered via
``frappe.db.after_commit`` -- so the Bin quantity observed is the final,
durable value rather than a value from an in-flight transaction.

``_collect_stock_pairs`` is a pure, Frappe-independent helper (it only
reads dict-like attributes off the passed document) so its filtering
logic -- in particular that Sales/Purchase Invoice rows are only queued
when ``update_stock`` is enabled -- can be unit tested without a live
Frappe/ERPNext site. Frappe itself is only imported inside the functions
that actually touch the database.
"""

import functools

LOW_STOCK_THRESHOLD = 10
IMPORTANT_ITEM_FIELD = "important_item"
PURCHASE_MANAGER_ROLE = "Purchase Manager"


def _collect_stock_pairs(doc):
    """Return the set of (item_code, warehouse) pairs whose Bin quantity
    this submitted/cancelled document actually moves.

    Sales Invoice and Purchase Invoice only move stock -- and therefore are
    only worth checking -- when ``update_stock`` is enabled; without it
    those invoices never touch a Bin and must not queue a check.

    Pure function: works against any dict-like ``doc`` (plain dict or a
    real Frappe Document) and never touches the database.
    """
    pairs = set()
    doctype = doc.get("doctype") if hasattr(doc, "get") else getattr(doc, "doctype", None)
    rows = doc.get("items") or []

    if doctype in ("Sales Invoice", "Purchase Invoice"):
        if not doc.get("update_stock"):
            return pairs
        for row in rows:
            item_code = row.get("item_code")
            warehouse = row.get("warehouse") or doc.get("set_warehouse")
            if item_code and warehouse:
                pairs.add((item_code, warehouse))
    elif doctype in ("Delivery Note", "Purchase Receipt"):
        for row in rows:
            item_code = row.get("item_code")
            warehouse = row.get("warehouse")
            if item_code and warehouse:
                pairs.add((item_code, warehouse))
    elif doctype == "Stock Entry":
        for row in rows:
            item_code = row.get("item_code")
            if not item_code:
                continue
            if row.get("s_warehouse"):
                pairs.add((item_code, row.get("s_warehouse")))
            if row.get("t_warehouse"):
                pairs.add((item_code, row.get("t_warehouse")))
    elif doctype == "Stock Reconciliation":
        for row in rows:
            item_code = row.get("item_code")
            warehouse = row.get("warehouse")
            if item_code and warehouse:
                pairs.add((item_code, warehouse))

    return pairs


def _notify_purchase_managers(item_code, warehouse, qty):
    """Create a Notification Log for every enabled user with the Purchase
    Manager role so each of them gets a real, queryable alert."""
    import frappe

    user_names = frappe.get_all(
        "Has Role",
        filters={"role": PURCHASE_MANAGER_ROLE, "parenttype": "User"},
        pluck="parent",
    )
    if not user_names:
        return

    enabled_users = frappe.get_all(
        "User",
        filters={"name": ["in", user_names], "enabled": 1},
        pluck="name",
    )

    subject = (
        f"Low stock alert: {item_code} in {warehouse} is below "
        f"{LOW_STOCK_THRESHOLD} (current qty: {qty})"
    )

    for user in enabled_users:
        frappe.get_doc(
            {
                "doctype": "Notification Log",
                "subject": subject,
                "for_user": user,
                "type": "Alert",
                "document_type": "Item",
                "document_name": item_code,
            }
        ).insert(ignore_permissions=True)

    if enabled_users:
        frappe.db.commit()


def _check_pairs(pairs):
    import frappe

    for item_code, warehouse in pairs:
        if not frappe.db.get_value("Item", item_code, IMPORTANT_ITEM_FIELD):
            continue
        qty = (
            frappe.db.get_value(
                "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
            )
            or 0
        )
        if qty < LOW_STOCK_THRESHOLD:
            _notify_purchase_managers(item_code, warehouse, qty)


def queue_low_stock_check(doc, method=None):
    """Doc event handler: register a post-commit Bin check for every stock
    pair this submitted/cancelled transaction actually moves."""
    import frappe

    pairs = _collect_stock_pairs(doc)
    if not pairs:
        return
    frappe.db.after_commit.add(functools.partial(_check_pairs, pairs))
