"""Sales Invoice server-side validation: selling rate vs valuation rate.

Requirement: prevent submitting a Sales Invoice when the selling rate is
below the item's valuation rate, unless the acting user has the authorized
override role.

This module is registered against the Sales Invoice ``validate`` hook in
``hooks.py`` (so it also blocks the earlier draft save, which is a stricter
guarantee than blocking submit alone -- a document that never validates can
never reach docstatus == 1). Frappe is imported lazily inside each function
so this module stays importable (for static/unit checks) even when Frappe
is not installed in the local sandbox; the real app only ever calls these
functions from inside a live Frappe/ERPNext request or ``bench execute``
context.

Currency / UOM correctness
---------------------------
ERPNext Sales Invoice ``rate`` is expressed in the invoice's *transaction*
currency, per Sales UOM. ``valuation_rate`` (read here from the item's
``Bin``) is expressed in *Company* currency, per Stock UOM. These two
numbers must never be compared directly.

* ``base_rate`` = ``rate * conversion_rate`` is the selling rate converted
  to Company currency, still per Sales UOM.
* ``conversion_factor`` on a Sales Invoice Item is always defined as the
  number of Stock-UOM units contained in ONE Sales-UOM unit (for example,
  1 Box == 10 Nos means ``conversion_factor`` == 10). That direction --
  Stock-UOM units per one Sales-UOM unit -- is the only correct reading of
  this field anywhere in this module, its comments, and its tests.
* The valuation floor, expressed per Sales UOM, is therefore
  ``valuation_rate * conversion_factor``, and ``base_rate`` is compared
  against that floor. Equivalently, ``base_rate / conversion_factor``
  (selling rate in Company currency per Stock UOM) is compared against the
  bare ``valuation_rate``.
"""

# The Role that is authorized to override (submit below valuation) this
# selling-rate check. Shipped as fixture metadata in
# synthetic_build_target_app/fixtures/role.json.
OVERRIDE_ROLE = "Selling Rate Override"


def _user_has_override_role(user=None):
    import frappe

    user = user or frappe.session.user
    return OVERRIDE_ROLE in frappe.get_roles(user)


def _get_item_valuation_rate(item_code, warehouse):
    """Return the Company-currency valuation rate per Stock UOM for
    ``item_code`` at ``warehouse``, or ``None`` when it cannot be
    determined (e.g. no Bin row yet, or no warehouse on the row)."""
    import frappe

    if not item_code or not warehouse:
        return None

    return frappe.db.get_value(
        "Bin", {"item_code": item_code, "warehouse": warehouse}, "valuation_rate"
    )


def get_floor_per_sales_uom(valuation_rate, conversion_factor):
    """The valuation floor, per Sales UOM: valuation_rate (per Stock UOM)
    multiplied by conversion_factor, where conversion_factor is the number
    of Stock-UOM units contained in ONE Sales-UOM unit."""
    return (valuation_rate or 0) * (conversion_factor or 1)


def validate_selling_rate_against_valuation(doc, method=None):
    """Registered against the Sales Invoice ``validate`` hook.

    Blocks saving (and therefore submitting) whenever any invoice line's
    selling rate, converted to Company currency and expressed per Sales
    UOM (``base_rate``), falls below that item's valuation floor for the
    same Sales UOM (``valuation_rate * conversion_factor``, where
    ``conversion_factor`` is the number of Stock-UOM units contained in
    ONE Sales-UOM unit) -- unless the acting user has the
    ``Selling Rate Override`` role.
    """
    import frappe

    if _user_has_override_role():
        return

    for item in doc.get("items") or []:
        valuation_rate = _get_item_valuation_rate(item.item_code, item.warehouse)
        if not valuation_rate:
            # Nothing to validate against (e.g. no Bin for this
            # item/warehouse combination yet).
            continue

        conversion_factor = item.conversion_factor or 1
        base_rate = item.base_rate
        if base_rate in (None, 0) and item.rate:
            base_rate = item.rate * (doc.conversion_rate or 1)

        floor_per_sales_uom = get_floor_per_sales_uom(valuation_rate, conversion_factor)

        if (base_rate or 0) < floor_per_sales_uom:
            frappe.throw(
                (
                    "Row #{idx}: the selling rate for item {item_code} is below its "
                    "valuation rate. Selling rate is {base_rate} per {uom} "
                    "(Company currency), but the valuation floor for that Sales "
                    "UOM is {floor} ({valuation_rate} per Stock UOM x "
                    "{conversion_factor}). Submitting below valuation requires "
                    "the '{override_role}' role."
                ).format(
                    idx=item.idx,
                    item_code=item.item_code,
                    base_rate=base_rate,
                    uom=item.uom or item.stock_uom,
                    floor=floor_per_sales_uom,
                    valuation_rate=valuation_rate,
                    conversion_factor=conversion_factor,
                    override_role=OVERRIDE_ROLE,
                ),
                title="Selling Rate Below Valuation",
            )
