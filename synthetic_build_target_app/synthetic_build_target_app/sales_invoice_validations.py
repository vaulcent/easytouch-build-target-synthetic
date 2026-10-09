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
"""

import frappe
from frappe import _

#: Role that is authorized to override the selling-rate-below-valuation
#: check and submit the Sales Invoice anyway.
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
