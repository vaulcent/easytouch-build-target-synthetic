"""Owner Daily Business Dashboard -- single-screen owner Script Report.

Goal: one screen where the business owner can see, for a given date and a
mandatory Company (base-currency figures are only meaningful for one
Company at a time): today's sales, expenses, cash collected, mobile money
collected, outstanding customers (names + their real outstanding
balances, not merely a count), and current profit.

Implemented as a standard Frappe Script Report (synced automatically from
this module's ``report/`` folder on ``bench migrate``) so there is
nothing to publish/deploy beyond the ordinary app migration (see the
requirement's "Non-goals": no automatic publication/deployment).

Every figure is read live from real submitted ERPNext documents / ledger
rows, in the selected Company's base currency:

* **Today's Sales** -- sum of submitted ``Sales Invoice.base_grand_total``
  (base-currency, so a foreign-currency invoice with a non-unit exchange
  rate is converted correctly instead of double counting its raw
  transaction-currency total) for the filtered date + Company.
* **Expenses** -- ``debit - credit`` on real ``GL Entry`` rows (``debit``/
  ``credit`` are already company-currency columns on GL Entry) posted
  against any non-group Expense-root-type Account of the Company, for the
  filtered date. Reading the real GL ledger (rather than one hardcoded
  source doctype) also picks up Journal Entry expense postings, Expense
  Claims, Purchase Invoices, stock valuation cost of goods sold, etc.
* **Cash Collected** -- sum of submitted ``Payment Entry.base_paid_amount``
  where ``payment_type = "Receive"`` and ``mode_of_payment = "Cash"``, for
  the filtered date + Company.
* **Mobile Money Collected** -- same, but for every Mode of Payment in
  ``MOBILE_MONEY_MODES_OF_PAYMENT`` that actually exists on this site
  (verified live site context: Nasiib Trading Co. uses "EVC Plus",
  "Zaad", and "eDahab" as its real mobile-money Mode of Payment masters;
  any mode not present on a given site is simply skipped, never an
  error -- no master literally named "Mobile Money" is assumed to exist).
* **Outstanding Customers** -- every Customer with a positive, currently
  open balance, read from real ``Payment Ledger Entry`` rows (``amount``
  is already in Company base currency; ``delinked = 0`` excludes entries
  cancelled/reversed transactions left behind), for the Company. This is
  a current snapshot (not scoped to the date filter), matching how "who
  still owes us money" is actually used by an owner. Both the customer
  name and their real outstanding amount are shown -- a bare count is not
  sufficient.
* **Current Profit** -- ERPNext's own native profit definition in the
  Company's base currency: (Income account ``credit - debit``) minus
  (Expense account ``debit - credit``) on real GL Entry rows for the
  filtered date, i.e. the same Income-less-Expense Profit & Loss
  calculation ERPNext's own P&L report uses -- not simply "sales minus a
  hand-picked set of expenses".

The five aggregate figures above are returned as Script Report
``report_summary`` cards (the real single-screen "dashboard" surface);
the tabular rows are the outstanding-customer list itself.

NOTE on Frappe v16 aggregates: ``frappe.get_all``/``frappe.get_list``/
``frappe.db.get_value`` reject SQL function strings (e.g. ``"sum(x)"``)
passed as the ``fields``/``fieldname`` argument. Every aggregate below is
therefore computed with a parameterized ``frappe.db.sql`` query using
``COALESCE(SUM(...), 0)`` instead.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, nowdate

#: Real Mode of Payment masters used for mobile-money receipts (verified
#: live site context for Nasiib Trading Co.). "Cash" is tracked as its own
#: separate metric and is never included here.
MOBILE_MONEY_MODES_OF_PAYMENT = ("EVC Plus", "Zaad", "eDahab")

OUTSTANDING_BALANCE_EPSILON = 0.005


def execute(filters=None):
    filters = frappe._dict(filters or {})
    company = filters.get("company")
    if not company:
        frappe.throw(
            "Company is required: every figure on this dashboard is a "
            "base-currency amount, which is only meaningful for one "
            "Company at a time."
        )
    date = filters.get("date") or nowdate()

    columns = _get_columns()
    outstanding_rows, outstanding_total = _get_outstanding_customers(company)
    report_summary = _get_report_summary(date, company, outstanding_total)
    return columns, outstanding_rows, None, None, report_summary


def _get_columns():
    return [
        {
            "label": "Customer",
            "fieldname": "customer",
            "fieldtype": "Link",
            "options": "Customer",
            "width": 220,
        },
        {
            "label": "Customer Name",
            "fieldname": "customer_name",
            "fieldtype": "Data",
            "width": 200,
        },
        {
            "label": "Outstanding Amount (Company Base Currency)",
            "fieldname": "outstanding_amount",
            "fieldtype": "Currency",
            "width": 260,
        },
    ]


def _get_report_summary(date, company, outstanding_total):
    currency = _get_company_currency(company)
    sales = _sum_sales_invoice_base_grand_total(date, company)
    cash_collected = _sum_received_payments_base(date, company, ("Cash",))
    mobile_money_collected = _sum_received_payments_base(
        date, company, MOBILE_MONEY_MODES_OF_PAYMENT
    )
    income_total = _sum_gl_root_type(date, company, "Income", credit_minus_debit=True)
    expense_total = _sum_gl_root_type(
        date, company, "Expense", credit_minus_debit=False
    )
    current_profit = flt(income_total) - flt(expense_total)

    def _card(label, value):
        return {
            "label": "{0} ({1})".format(label, currency),
            "value": flt(value),
            "datatype": "Currency",
            "fieldname": label.lower().replace(" ", "_").replace("'", ""),
        }

    return [
        _card("Today's Sales", sales),
        _card("Expenses", expense_total),
        _card("Cash Collected", cash_collected),
        _card("Mobile Money Collected", mobile_money_collected),
        _card("Outstanding Customers Total", outstanding_total),
        _card("Current Profit", current_profit),
    ]


def _get_company_currency(company):
    return frappe.db.get_value("Company", company, "default_currency")


def _sum_sales_invoice_base_grand_total(date, company):
    """Sum submitted Sales Invoice base_grand_total (Company currency)."""
    result = frappe.db.sql(
        "select coalesce(sum(base_grand_total), 0) from `tabSales Invoice` "
        "where docstatus = 1 and posting_date = %s and company = %s",
        (date, company),
    )
    return flt(result[0][0]) if result else 0.0


def _sum_received_payments_base(date, company, modes_of_payment):
    """Sum submitted Payment Entry base_paid_amount for a set of modes.

    Any mode in ``modes_of_payment`` that has no Mode of Payment master on
    this site is silently skipped (never an error).
    """
    existing_modes = tuple(
        mode
        for mode in modes_of_payment
        if frappe.db.exists("Mode of Payment", mode)
    )
    if not existing_modes:
        return 0.0

    result = frappe.db.sql(
        "select coalesce(sum(base_paid_amount), 0) from `tabPayment Entry` "
        "where docstatus = 1 and payment_type = %s and posting_date = %s "
        "and company = %s and mode_of_payment in %s",
        ("Receive", date, company, existing_modes),
    )
    return flt(result[0][0]) if result else 0.0


def _sum_gl_root_type(date, company, root_type, credit_minus_debit):
    """Sum real GL Entry postings against one root_type's leaf Accounts.

    ``debit``/``credit`` on GL Entry are already Company base-currency
    columns, so this is correct regardless of any individual
    transaction's own document currency.
    """
    accounts = frappe.db.get_list(
        "Account",
        filters={"root_type": root_type, "is_group": 0, "company": company},
        pluck="name",
    )
    if not accounts:
        return 0.0

    aggregate_expression = (
        "coalesce(sum(credit), 0) - coalesce(sum(debit), 0)"
        if credit_minus_debit
        else "coalesce(sum(debit), 0) - coalesce(sum(credit), 0)"
    )
    result = frappe.db.sql(
        "select {0} from `tabGL Entry` where is_cancelled = 0 and "
        "posting_date = %s and company = %s and account in %s".format(
            aggregate_expression
        ),
        (date, company, tuple(accounts)),
    )
    if not result or result[0][0] is None:
        return 0.0
    return flt(result[0][0])


def _get_outstanding_customers(company):
    """Real, currently-open per-customer balances (Company base currency).

    Reads ``Payment Ledger Entry.amount`` (already base currency) rather
    than any document-currency ``outstanding_amount`` field, filtered to
    active (``delinked = 0``) entries for this Company, grouped by
    ``party``. Both the customer name and the real balance are returned
    -- draft/cancelled/fully-settled invoices never post (or net out to
    zero in) the Payment Ledger, so they are naturally excluded.
    """
    rows = frappe.db.sql(
        "select party, coalesce(sum(amount), 0) as balance "
        "from `tabPayment Ledger Entry` "
        "where party_type = %s and company = %s and delinked = 0 "
        "group by party",
        ("Customer", company),
        as_dict=True,
    )

    data = []
    total = 0.0
    for row in rows:
        balance = flt(row["balance"])
        if balance <= OUTSTANDING_BALANCE_EPSILON:
            continue
        customer = row["party"]
        customer_name = frappe.db.get_value("Customer", customer, "customer_name")
        total += balance
        data.append(
            {
                "customer": customer,
                "customer_name": customer_name,
                "outstanding_amount": balance,
            }
        )

    data.sort(key=lambda r: r["outstanding_amount"], reverse=True)
    return data, total
