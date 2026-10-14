"""Server-side validation: block submitting a Sales Invoice when any row's
selling rate is below the item's valuation rate, unless the acting user
holds the ``Selling Rate Override`` role.

Registered in hooks.py as a ``before_submit`` doc_event for Sales Invoice,
so it only blocks the submit transition (not ordinary draft saves), which
matches the "prevents submitting" requirement precisely.

Currency / UOM correctness
---------------------------
ERPNext's Sales Invoice Item ``rate`` is expressed in the invoice's
transaction currency and per the row's Sales UOM. ``valuation_rate`` (read
here from the Bin for the row's item/warehouse) is always expressed in the
Company's base currency and per the item's Stock UOM. Comparing those two
numbers directly is wrong whenever the invoice currency differs from the
Company currency, or the row's Sales UOM differs from the Stock UOM.

This handler always compares Company-currency amounts on the same
per-Sales-UOM basis:

1. Convert the row's selling rate to Company currency, preferring the
   row's own ``base_rate`` (already converted by ERPNext using the
   document's ``conversion_rate``); fall back to
   ``rate * conversion_rate`` if ``base_rate`` has not been computed yet.
2. Compare that Company-currency, per-Sales-UOM amount against the
   valuation rate scaled up to the same per-Sales-UOM basis:
   ``valuation_rate * conversion_factor``.

   ``conversion_factor`` is the number of Stock UOM units contained in one
   Sales UOM unit (for example, a "Box" Sales UOM with
   ``conversion_factor`` 10 means one Box contains 10 "Nos" Stock UOM
   units -- ten Stock-UOM units per one Sales-UOM unit, never the other
   way around). Multiplying the per-Stock-UOM valuation rate by that
   factor yields the equivalent valuation floor per Sales UOM.

Equivalently, dividing ``base_rate`` by ``conversion_factor`` yields the
Company-currency, per-Stock-UOM selling rate, which can be compared
directly against ``valuation_rate`` (also Company currency, per Stock
UOM). Both forms of the comparison are mathematically identical; this
handler uses the per-Sales-UOM form.
"""

import frappe

OVERRIDE_ROLE = "Selling Rate Override"


def _get_valuation_rate(item_code, warehouse):
    """Return the Company-currency valuation rate per Stock UOM for this
    item/warehouse, read from the real Bin maintained by ERPNext's stock
    ledger (never guessed or hardcoded)."""
    if not item_code or not warehouse:
        return 0
    return (
        frappe.db.get_value(
            "Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"
        )
        or 0
    )


def user_has_override_role(user=None):
    """Return True if the given (or current session) user holds the
    ``Selling Rate Override`` role."""
    roles = frappe.get_roles(user) if user else frappe.get_roles()
    return OVERRIDE_ROLE in roles


def validate_selling_rate_against_valuation(doc, method=None):
    """Block submission when any row sells below its valuation floor,
    unless the acting user holds the ``Selling Rate Override`` role.

    Every comparison here is Company currency, per Sales UOM:
    ``base_rate`` (or ``rate * conversion_rate`` when ``base_rate`` is not
    yet populated) against ``valuation_rate * conversion_factor``.
    """
    if doc.doctype != "Sales Invoice":
        return

    if user_has_override_role():
        return

    conversion_rate = doc.get("conversion_rate") or 1

    violations = []
    for row in doc.get("items") or []:
        warehouse = row.get("warehouse") or doc.get("set_warehouse")
        valuation_rate = _get_valuation_rate(row.get("item_code"), warehouse)
        if not valuation_rate:
            # No real valuation evidence for this item/warehouse yet
            # (e.g. never received into stock): nothing to floor against.
            continue

        conversion_factor = row.get("conversion_factor") or 1
        base_rate = row.get("base_rate")
        if not base_rate:
            base_rate = (row.get("rate") or 0) * conversion_rate

        valuation_floor = valuation_rate * conversion_factor

        if base_rate < valuation_floor:
            violations.append(
                frappe._(
                    "Row #{0}: selling rate for item {1} ({2} {3} per Sales "
                    "UOM, Company currency) is below the valuation floor "
                    "({4} {3} per Sales UOM = valuation rate {5} x "
                    "conversion factor {6})."
                ).format(
                    row.idx,
                    row.item_code,
                    base_rate,
                    frappe.db.get_value("Company", doc.company, "default_currency"),
                    valuation_floor,
                    valuation_rate,
                    conversion_factor,
                )
            )

    if violations:
        frappe.throw(
            "<br>".join(violations),
            title=frappe._("Selling Rate Below Valuation Rate"),
        )
