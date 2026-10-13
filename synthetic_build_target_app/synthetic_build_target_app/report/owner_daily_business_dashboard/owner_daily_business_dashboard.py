"""Owner Daily Business Dashboard -- single-screen owner Script Report.

Goal: one screen where the business owner can see, for a given date (and
optional company): today's sales, expenses, cash collected, mobile money
collected, the number of customers with outstanding (unpaid) balances, and
current profit (today's sales minus today's expenses).

Implemented as a standard Frappe Script Report (synced automatically from
this module's ``report/`` folder on ``bench migrate`` -- the same
mechanism ERPNext itself uses to ship its own script reports) rather than
a new DocType, dashboard page, or background job, so there is nothing to
publish/deploy beyond the ordinary app migration (see the requirement's
"Non-goals": no automatic publication/deployment).

Every figure is read live from real submitted ERPNext documents, never
from any cached/denormalized snapshot:

* **Today's Sales** -- sum of submitted ``Sales Invoice.grand_total`` for
  the filtered date (+ company).
* **Expenses** -- sum of (debit - credit) ``GL Entry`` postings against
  any non-group ``Account`` whose ``root_type`` is ``"Expense"``, for the
  filtered date (+ company). Reading the real GL ledger (rather than
  hardcoding a single source doctype such as Purchase Invoice) means this
  also picks up Journal Entry expense postings, Expense Claims, etc. --
  any real ERPNext transaction that books an expense.
* **Cash Collected** / **Mobile Money Collected** -- sum of submitted
  ``Payment Entry.paid_amount`` where ``payment_type = "Receive"`` and
  ``mode_of_payment`` is ``"Cash"`` / ``"Mobile Money"`` respectively, for
  the filtered date (+ company). If the "Mobile Money" Mode of Payment
  master does not exist yet on a given site, that figure is simply ``0``
  (never an error).
* **Outstanding Customers** -- count of distinct customers with at least
  one submitted Sales Invoice whose ``outstanding_amount`` is greater
  than zero right now (+ company). This is a current snapshot, not scoped
  to the date filter, matching how "who still owes us money" is actually
  used by an owner.
* **Current Profit** -- Today's Sales minus Expenses for the filtered
  date.

The ``date`` filter defaults to "Today" and the ``company`` filter is
optional (omit it to see figures across every company).

NOTE on Frappe v16 aggregates: ``frappe.get_all``/``frappe.get_list``/
``frappe.db.get_value`` reject SQL function strings (e.g. ``"sum(x)"``)
passed as the ``fields``/``fieldname`` argument. Every aggregate below is
therefore computed with a parameterized ``frappe.db.sql`` query using
``COALESCE(SUM(...), 0)`` instead.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, nowdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    date = filters.get("date") or nowdate()
    company = filters.get("company")

    columns = _get_columns()
    data = [_get_dashboard_row(date, company)]
    return columns, data


def _get_columns():
    return [
        {
            "label": "Today's Sales",
            "fieldname": "todays_sales",
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "label": "Expenses",
            "fieldname": "expenses",
            "fieldtype": "Currency",
            "width": 130,
        },
        {
            "label": "Cash Collected",
            "fieldname": "cash_collected",
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "label": "Mobile Money Collected",
            "fieldname": "mobile_money_collected",
            "fieldtype": "Currency",
            "width": 190,
        },
        {
            "label": "Outstanding Customers",
            "fieldname": "outstanding_customers",
            "fieldtype": "Int",
            "width": 170,
        },
        {
            "label": "Current Profit",
            "fieldname": "current_profit",
            "fieldtype": "Currency",
            "width": 150,
        },
    ]


def _get_dashboard_row(date, company):
    sales = _sum_sales_invoice_grand_total(date, company)
    expenses = _sum_expense_gl_entries(date, company)
    cash_collected = _sum_received_payments(date, company, "Cash")
    mobile_money_collected = _sum_received_payments(date, company, "Mobile Money")
    outstanding_customers = _count_outstanding_customers(company)

    return {
        "todays_sales": sales,
        "expenses": expenses,
        "cash_collected": cash_collected,
        "mobile_money_collected": mobile_money_collected,
        "outstanding_customers": outstanding_customers,
        "current_profit": flt(sales) - flt(expenses),
    }


def _sum_sales_invoice_grand_total(date, company):
    """Sum submitted Sales Invoice grand_total for one posting date."""
    conditions = ["docstatus = 1", "posting_date = %s"]
    values = [date]
    if company:
        conditions.append("company = %s")
        values.append(company)

    where_clause = " and ".join(conditions)
    result = frappe.db.sql(
        "select coalesce(sum(grand_total), 0) from `tabSales Invoice` "
        "where {0}".format(where_clause),
        values,
    )
    return flt(result[0][0]) if result else 0.0


def _sum_received_payments(date, company, mode_of_payment):
    """Sum submitted Payment Entry receipts for one Mode of Payment."""
    if not frappe.db.exists("Mode of Payment", mode_of_payment):
        return 0.0

    conditions = [
        "docstatus = 1",
        "payment_type = %s",
        "posting_date = %s",
        "mode_of_payment = %s",
    ]
    values = ["Receive", date, mode_of_payment]
    if company:
        conditions.append("company = %s")
        values.append(company)

    where_clause = " and ".join(conditions)
    result = frappe.db.sql(
        "select coalesce(sum(paid_amount), 0) from `tabPayment Entry` "
        "where {0}".format(where_clause),
        values,
    )
    return flt(result[0][0]) if result else 0.0


def _sum_expense_gl_entries(date, company):
    """Sum real GL Entry postings against non-group Expense accounts."""
    account_filters = {"root_type": "Expense", "is_group": 0}
    if company:
        account_filters["company"] = company

    expense_accounts = frappe.db.get_list(
        "Account", filters=account_filters, pluck="name"
    )
    if not expense_accounts:
        return 0.0

    conditions = ["is_cancelled = 0", "posting_date = %s"]
    values = [date]
    if company:
        conditions.append("company = %s")
        values.append(company)
    conditions.append("account in %s")
    values.append(tuple(expense_accounts))

    where_clause = " and ".join(conditions)
    result = frappe.db.sql(
        "select coalesce(sum(debit), 0) - coalesce(sum(credit), 0) "
        "from `tabGL Entry` where {0}".format(where_clause),
        values,
    )
    if not result or result[0][0] is None:
        return 0.0
    return flt(result[0][0])


def _count_outstanding_customers(company):
    """Count distinct customers currently holding an unpaid Sales Invoice."""
    filters = {"docstatus": 1, "outstanding_amount": [">", 0]}
    if company:
        filters["company"] = company

    customers = frappe.db.get_list("Sales Invoice", filters=filters, pluck="customer")
    return len(set(customers))
