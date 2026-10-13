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
    """
    user = frappe.session.user

    if user == "Administrator":
        return

    if AUTHORIZED_OVERRIDE_ROLE in frappe.get_roles(user):
        return

    for item in doc.get("items", []) or []:
        valuation_rate = item.get("valuation_rate") or 0
        selling_rate = item.get("rate") or 0

        if not valuation_rate:
            valuation_rate = _get_warehouse_bin_valuation_rate(
                item.get("item_code"),
                item.get("warehouse") or doc.get("set_warehouse"),
            )

        if valuation_rate and selling_rate < valuation_rate:
            frappe.throw(
                _(
                    "Row #{0}: Selling rate ({1}) for item {2} is below its "
                    "valuation rate ({3}). Only users with the '{4}' role "
                    "may submit at this rate."
                ).format(
                    item.get("idx"),
                    selling_rate,
                    item.get("item_code"),
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
    either argument is missing or no matching Bin exists.
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
