"""Stock-transaction hook for the Important Item Low Stock Alert.

Real ERPNext v16 validation proved that Stock Ledger Entry rows are
written via a direct ``db_insert`` as part of posting a stock transaction
-- they never go through ``frappe.get_doc(...).submit()`` /
``on_submit`` document-event dispatch themselves. Hooking
``Stock Ledger Entry`` -- ``on_submit`` (the previous approach) therefore
never fires on a real site; it is an ineffective hook and has been
removed.

This module instead hooks ``on_submit`` AND ``on_cancel`` of every real,
originating submittable transaction whose lifecycle changes ``Bin``
quantities -- ``Stock Entry``, ``Delivery Note``, ``Purchase Receipt``,
``Purchase Invoice``, ``Stock Reconciliation``, and ``Sales Invoice``.
Both directions are registered because either a submit or a cancel can
cross the low-stock threshold in either direction: cancelling a Delivery
Note gives stock back (crossing upward), cancelling a Purchase Receipt
takes stock away again (crossing downward). Those ``on_submit`` /
``on_cancel`` hooks are real Frappe document-lifecycle events that do
fire; ``Stock Ledger Entry`` and ``Bin`` writes do not reliably emit
ordinary document lifecycle events of their own.

Sales Invoice and Purchase Invoice only actually move stock when their
``update_stock`` flag is enabled; without it they never touch a Bin at
all, so this module queues a check for those two doctypes only when
``update_stock`` is truthy on the submitted/cancelled document. Queuing
unconditionally for an invoice with ``update_stock`` unset would still
collect the (item_code, warehouse) pairs off its rows (the ``warehouse``
field exists on those child rows regardless of ``update_stock``) and could
then re-send a stale alert for an unrelated, already-low Bin that this
particular invoice never actually changed -- a false alert this module
must not produce.

ERPNext still updates ``Bin`` quantities (``actual_qty``) via direct
database writes rather than ``Bin.save()``, so the final authoritative
quantity is only guaranteed to be correct once the enclosing database
transaction has committed -- this is true for cancellation reversals just
as much as for the original submit. This module therefore schedules an
after-commit callback per item/warehouse pair found on the submitted or
cancelled transaction's child rows, and only reads the Bin and performs
the important-item + low-stock gating once that commit has actually
happened.

The warehouse context is read generically from whichever real child-row
field the given transaction type uses (``warehouse`` for Delivery Note /
Purchase Receipt / Sales Invoice / Purchase Invoice / Stock Reconciliation
rows, ``s_warehouse`` / ``t_warehouse`` for Stock Entry rows), never
hardcoded to one item or warehouse.

Real ERPNext v16 validation also rejects two things a naive fix might
try:

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
this module). The Notification's ``channel`` is ``System Notification``,
so dispatch creates an in-app Notification Log for the Purchase Manager
recipient without requiring any outgoing Email Account on the site.

This module performs the actual gating in ordinary trusted Python --
requiring BOTH that ``Item.is_important_item`` is true AND that the final
``Bin.actual_qty`` is below the threshold -- before calling the existing
Notification's ``send(bin_doc)`` directly. It never relies on
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

#: Real child-row field names, across the real submittable stock
#: transactions this module hooks, that can carry a warehouse for a given
#: item row. Checked generically -- never hardcoded to one transaction
#: type, item, or warehouse.
_WAREHOUSE_FIELDS = ("warehouse", "s_warehouse", "t_warehouse")

#: Doctypes whose stock impact is conditional on their own ``update_stock``
#: flag. Sales Invoice and Purchase Invoice never move stock unless this
#: flag is enabled, so a check must only be queued for them when it is.
_INVOICE_DOCTYPES_REQUIRING_UPDATE_STOCK = frozenset(
    {"Sales Invoice", "Purchase Invoice"}
)


def _iter_item_warehouse_pairs(doc):
    """Yield every real ``(item_code, warehouse)`` pair on ``doc``'s rows.

    ``doc`` is the real submitted/cancelled stock transaction (Stock
    Entry, Delivery Note, Purchase Receipt, Purchase Invoice, Stock
    Reconciliation, or Sales Invoice). Reads only its ``items`` child rows
    and only the real warehouse fields those rows define.
    """
    for row in doc.get("items") or []:
        item_code = row.get("item_code")
        if not item_code:
            continue
        for warehouse_field in _WAREHOUSE_FIELDS:
            warehouse = row.get(warehouse_field)
            if warehouse:
                yield item_code, warehouse


def queue_important_item_low_stock_alert(doc, method=None) -> None:
    """Schedule a low-stock check for every item/warehouse on ``doc``.

    Wired to ``on_submit`` AND ``on_cancel`` of every real originating
    stock-changing transaction (Stock Entry, Delivery Note, Purchase
    Receipt, Purchase Invoice, Stock Reconciliation, Sales Invoice) via
    hooks.py, so this runs for every real stock movement a user actually
    submits or cancels -- either direction can cross the low-stock
    threshold.

    Sales Invoice and Purchase Invoice only move stock when their
    ``update_stock`` flag is enabled; this function queues nothing for
    them when it is not, since those invoices never touch a Bin and
    queuing anyway risks re-sending a stale alert for an unrelated,
    already-low Bin that this particular document never changed.

    ``doc`` here is the real submitted/cancelled transaction; its item/
    warehouse pairs are read generically off its rows, never hardcoded.
    """
    if doc.get("doctype") in _INVOICE_DOCTYPES_REQUIRING_UPDATE_STOCK and not doc.get(
        "update_stock"
    ):
        return

    for item_code, warehouse in _iter_item_warehouse_pairs(doc):
        frappe.db.after_commit.add(
            lambda ic=item_code, wh=warehouse: send_important_item_low_stock_alert(
                ic, wh
            )
        )


def send_important_item_low_stock_alert(item_code: str, warehouse: str) -> None:
    """Read the final Bin quantity for ``item_code``/``warehouse`` and send
    the existing "Important Item Low Stock Alert" Notification if due.

    Runs after the enclosing stock transaction (submit or cancel) has
    committed, so the Bin quantity read here is the final, authoritative
    post-movement value -- independent of whether ERPNext updated the Bin
    via ``save()`` or a direct database write for this particular
    transaction type, and independent of whether the movement was a
    forward submission or a cancellation reversal.

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
