"""General stock-ledger-compatible hook for the Important Item Low Stock Alert.

ERPNext updates ``Bin`` quantities (``actual_qty``) via direct database
writes as part of posting Stock Ledger Entries for Stock Entry, Delivery
Note, Purchase Receipt, Sales Invoice with ``update_stock``, and every other
stock transaction. Those direct writes do not go through ``Bin.save()``, so
the pre-existing "Important Item Low Stock Alert" Notification DocType --
configured with ``event = "Value Change"`` on the ``Bin`` DocType -- never
observes a change and therefore never fires on a real site.

To close that gap, this module hooks into ``Stock Ledger Entry`` --
``on_submit``, which fires for *every* real stock movement regardless of
which ERPNext transaction produced it, without hardcoding any specific
item, warehouse, or transaction type. It schedules an after-commit
callback: by the time the enclosing database transaction commits, ERPNext
has already finished updating the Bin for the affected item/warehouse, so
reading the Bin's quantity at that point reflects the final, authoritative
post-movement value. If that Bin's item is marked ``is_important_item`` and
the quantity is below the threshold encoded in the existing Notification's
own ``condition``, this module sends that *same* pre-existing Notification
document (reusing its condition, subject, message, warehouse context, and
Purchase Manager recipient role as-is) rather than duplicating the
threshold/recipient logic here.
"""

from __future__ import annotations

import frappe
from frappe.email.doctype.notification.notification import get_context

#: Name of the pre-existing Notification document this module reuses.
IMPORTANT_ITEM_LOW_STOCK_ALERT = "Important Item Low Stock Alert"


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

    # Fetch the real, final Bin document so the Notification's own
    # condition/subject/message template (which already references
    # doc.item_code, doc.warehouse, and doc.actual_qty) evaluates against
    # the authoritative post-commit quantity.
    bin_doc = frappe.get_doc("Bin", bin_name)

    context = get_context(bin_doc)
    context.update({"frappe": frappe})
    if notification.condition and not frappe.safe_eval(
        notification.condition, None, context
    ):
        return

    notification.send(bin_doc)
