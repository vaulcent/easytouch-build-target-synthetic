"""General stock-ledger-compatible hook for the Important Item Low Stock Alert.

ERPNext updates ``Bin`` quantities (``actual_qty``) via direct database
writes as part of posting Stock Ledger Entries for Stock Entry, Delivery
Note, Purchase Receipt, Sales Invoice with ``update_stock``, and every other
stock transaction. Those direct writes do not go through ``Bin.save()``, so
a Notification configured with ``event = "Value Change"`` on the ``Bin``
DocType never observes a change and therefore never fires on a real site.

Real ERPNext v16 validation also rejects two things a naive fix might try:

* A Notification ``condition`` that references ``doc.is_important_item``
  on ``Bin`` -- ``Bin`` has no such field, so DocType metadata validation
  (run at save/migrate time) rejects the Notification outright.
* ``frappe.db`` access from inside a Notification's ``safe_eval``'d
  ``condition`` -- forbidden by the safe_eval sandbox.

``Notification.send(doc)`` also never evaluates ``Notification.condition``
on its own; it only renders the subject/message and dispatches. So the
existing "Important Item Low Stock Alert" Notification fixture is
configured with ``event = "Custom"`` (never auto-wired to fire on ordinary
Bin saves/value-changes) and a ``condition`` limited to a real Bin field
(``doc.actual_qty < 10``, used only for the Notification doctype's own
save/migrate-time self-check of the condition string -- never evaluated by
this module).

This module hooks into ``Stock Ledger Entry`` -- ``on_submit``, which
fires for *every* real stock movement regardless of which ERPNext
transaction produced it, without hardcoding any specific item, warehouse,
or transaction type. It schedules an after-commit callback: by the time
the enclosing database transaction commits, ERPNext has already finished
updating the Bin for the affected item/warehouse, so reading the Bin's
quantity at that point reflects the final, authoritative post-movement
value. This module then performs the actual gating in ordinary trusted
Python -- requiring BOTH that ``Item.is_important_item`` is true AND that
the final ``Bin.actual_qty`` is below the threshold -- before calling the
existing Notification's ``send(bin_doc)`` directly. It never relies on
``Notification.send`` to evaluate its stored condition, and never calls
``frappe.safe_eval`` on that condition string itself.
"""

from __future__ import annotations

import frappe

#: Name of the pre-existing Notification document this module reuses.
IMPORTANT_ITEM_LOW_STOCK_ALERT = "Important Item Low Stock Alert"

#: Real stock quantity threshold mirrored from the Notification's own
#: ``condition`` field (``doc.actual_qty < 10``), kept here as a plain
#: Python constant so this module never needs to evaluate that condition
#: string itself.
LOW_STOCK_THRESHOLD = 10


def queue_important_item_low_stock_alert(doc, method=None) -> None:
    """Schedule a low-stock check for ``doc``'s item/warehouse after commit.

    Wired to ``Stock Ledger Entry`` -- ``on_submit`` via hooks.py, so this
    runs for every real stock ledger posting produced by any ERPNext stock
    transaction. ``doc`` here is the Stock Ledger Entry being submitted;
    its ``item_code``/``warehouse`` are read generically, never hardcoded.
    """
    item_code = doc.get("item_code")
    warehouse = doc.get("warehouse")
    if not item_code or not warehouse:
        return

    frappe.db.after_commit.add(
        lambda: send_important_item_low_stock_alert(item_code, warehouse)
    )


def send_important_item_low_stock_alert(item_code: str, warehouse: str) -> None:
    """Read the final Bin quantity for ``item_code``/``warehouse`` and send
    the existing "Important Item Low Stock Alert" Notification if due.

    Runs after the enclosing stock ledger transaction has committed, so the
    Bin quantity read here is the final, authoritative post-movement value
    -- independent of whether ERPNext updated the Bin via ``save()`` or a
    direct database write for this particular transaction type.

    The gating decision is made entirely in ordinary trusted Python: BOTH
    ``Item.is_important_item`` must be true AND the final
    ``Bin.actual_qty`` must be below ``LOW_STOCK_THRESHOLD``. This never
    relies on ``Notification.send`` to evaluate its own ``condition``
    (which it does not do), and never calls ``frappe.safe_eval`` on the
    stored condition string.
    """
    if not frappe.db.exists("Notification", IMPORTANT_ITEM_LOW_STOCK_ALERT):
        return

    notification = frappe.get_cached_doc(
        "Notification", IMPORTANT_ITEM_LOW_STOCK_ALERT
    )
    if not notification.enabled:
        return

    bin_name = frappe.db.get_value(
        "Bin", {"item_code": item_code, "warehouse": warehouse}, "name"
    )
    if not bin_name:
        return

    # Fetch the real, final Bin document so the Notification's subject and
    # message template (which reference doc.item_code, doc.warehouse, and
    # doc.actual_qty) render against the authoritative post-commit
    # quantity.
    bin_doc = frappe.get_doc("Bin", bin_name)

    if bin_doc.actual_qty is None or bin_doc.actual_qty >= LOW_STOCK_THRESHOLD:
        return

    if not frappe.db.get_value("Item", item_code, "is_important_item"):
        return

    notification.send(bin_doc)
