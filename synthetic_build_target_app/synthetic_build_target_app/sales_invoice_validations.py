"""Server-side validation for Sales Invoice selling rate vs. valuation rate.

Requirement: prevent submitting a Sales Invoice when any item's selling rate
is below that item's valuation rate, unless the acting user holds the
authorized override role (``AUTHORIZED_OVERRIDE_ROLE``).

This module exposes a single validation function that is wired into two
validation lanes via ``hooks.py`` ``doc_events`` for the ``Sales Invoice``
DocType:

1. ``validate`` -- runs on every save (draft or otherwise), giving early
   feedback before the user attempts to submit.
2. ``before_submit`` -- runs immediately before submission and is the hard
   stop that actually prevents submitting an under-valuation-rate invoice
   without the override role.

Both lanes call the same function so the rule is enforced consistently and
idempotently; there is no duplicated validation logic to drift out of sync.

Each child row's own ``valuation_rate`` is normally populated by ERPNext's
standard pricing calculations, but it can be empty (for example on a
manually keyed-in row before those calculations run). When that happens,
this module falls back to reading the *real* current warehouse valuation
rate from the ``Bin`` for that ``item_code`` + the row's own ``warehouse``
(falling back to the invoice's ``set_warehouse`` only if the row itself has
no warehouse), instead of silently skipping the check for that row. No
item, warehouse, company, or invoice is ever hardcoded.

Currency and Sales-UOM handling
--------------------------------
ERPNext's Sales Invoice row ``rate`` is expressed in the invoice's own
transaction currency and per that row's *Sales* UOM. ``valuation_rate``
(whether read from the row itself or, as a fallback, from the warehouse
``Bin``) is always expressed in the Company's currency and per the item's
*Stock* UOM. Comparing those two numbers directly is only correct when the
invoice currency equals the Company currency AND the row's Sales UOM
equals the Stock UOM; in every other case a direct comparison silently
mixes different currencies and/or different units. This module instead:

* Converts the selling rate to Company currency using the row's own
  ``base_rate`` (ERPNext's standard ``rate * doc.conversion_rate``,
  already computed before this hook runs), falling back to that same
  multiplication only when ``base_rate`` has not yet been computed.
* Converts the per-Stock-UOM valuation rate into a per-Sales-UOM floor by
  multiplying it by the row's ``conversion_factor`` -- the number of
  Stock-UOM units contained in ONE Sales-UOM unit (for example, a "Box"
  Sales UOM with ``conversion_factor`` 10 means one Box contains 10
  Stock-UOM units; ``conversion_factor`` is never Sales-UOM units per one
  Stock-UOM unit).
* Compares ``base_rate`` (Company currency, per Sales UOM) against
  ``valuation_rate * conversion_factor`` (Company currency, per Sales
  UOM) -- both expressed in the same currency and the same unit.
"""

import frappe
from frappe import _

#: Role that is authorized to override the selling-rate-below-valuation
#: check and submit the Sales Invoice anyway. Provisioned idempotently as
#: a Role fixture (see fixtures/role.json + hooks.py ``fixtures``) so it
#: is assignable to users on a real site.
AUTHORIZED_OVERRIDE_ROLE = "Sales Invoice Rate Override"


def validate_selling_rate_against_valuation_rate(doc, method=None):
    """Raise if any item's selling rate is below its valuation rate.

    Administrators and users holding ``AUTHORIZED_OVERRIDE_ROLE`` are exempt
    from the check so authorized overrides can still be submitted.

    The comparison is always performed in Company currency, per Sales UOM:
    the row's ``base_rate`` (selling rate converted to Company currency)
    against ``valuation_rate * conversion_factor`` (the per-Stock-UOM
    valuation rate scaled up to a per-Sales-UOM floor, since
    ``conversion_factor`` is Stock-UOM units per one Sales-UOM unit).
    """
    user = frappe.session.user

    if user == "Administrator":
        return

    if AUTHORIZED_OVERRIDE_ROLE in frappe.get_roles(user):
        return

    conversion_rate = doc.get("conversion_rate") or 1

    for item in doc.get("items", []) or []:
        valuation_rate = item.get("valuation_rate") or 0

        if not valuation_rate:
            valuation_rate = _get_warehouse_bin_valuation_rate(
                item.get("item_code"),
                item.get("warehouse") or doc.get("set_warehouse"),
            )

        if not valuation_rate:
            continue

        # conversion_factor is the number of Stock-UOM units contained in
        # ONE Sales-UOM unit (e.g. 10 Nos per 1 Box) -- never the reverse.
        conversion_factor = item.get("conversion_factor") or 1

        # Selling rate converted to Company currency, per Sales UOM.
        # Prefer ERPNext's own already-computed base_rate; only compute it
        # ourselves (rate * conversion_rate) when base_rate is genuinely
        # absent (e.g. a minimally constructed row before standard
        # calculations have run).
        base_rate = item.get("base_rate")
        if base_rate is None:
            base_rate = (item.get("rate") or 0) * conversion_rate

        # Valuation-based floor converted to Company currency, per Sales
        # UOM: the per-Stock-UOM valuation rate scaled up by the number of
        # Stock-UOM units in one Sales-UOM unit.
        valuation_floor_per_sales_uom = valuation_rate * conversion_factor

        if base_rate < valuation_floor_per_sales_uom:
            frappe.throw(
                _(
                    "Row #{0}: Selling rate for item {1} (base rate {2} per "
                    "{3}, Company currency) is below its valuation-based "
                    "floor ({4} per {3}, Company currency, derived from a "
                    "valuation rate of {5} per Stock UOM). Only users with "
                    "the '{6}' role may submit at this rate."
                ).format(
                    item.get("idx"),
                    item.get("item_code"),
                    base_rate,
                    item.get("uom") or item.get("stock_uom"),
                    valuation_floor_per_sales_uom,
                    valuation_rate,
                    AUTHORIZED_OVERRIDE_ROLE,
                ),
                title=_("Selling Rate Below Valuation Rate"),
            )


def _get_warehouse_bin_valuation_rate(item_code, warehouse):
    """Read the real, current ``Bin.valuation_rate`` for item_code+warehouse.

    Used only as a fallback when a Sales Invoice child row's own
    ``valuation_rate`` is empty. Reads the live warehouse Bin instead of
    assuming any particular item, warehouse, or company. Returns ``0`` if
    either argument is missing or no matching Bin exists. The returned
    value is a per-Stock-UOM valuation rate in Company currency.
    """
    if not item_code or not warehouse:
        return 0

    return (
        frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            "valuation_rate",
        )
        or 0
    )
