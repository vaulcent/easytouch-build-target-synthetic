"""Tests for the "Owner Daily Business Dashboard" Script Report.

Requirement: one screen where the owner can see today's sales, expenses,
cash collected, mobile money collected, outstanding customers, and
current profit.

``TestOwnerDailyBusinessDashboardReportStaticWiring`` runs unconditionally
in this local sandbox (no Frappe) and only checks the report definition's
shape/wiring -- it is NOT behavioral evidence on its own.

``TestOwnerDailyBusinessDashboardReportFrappeBacked`` is the authoritative
behavior evidence: it seeds real submitted ERPNext documents on a live
Frappe/ERPNext v16 site and executes the report's own ``execute()``
function, asserting the returned figures. It skips only when Frappe is
unavailable in this local coding sandbox; it must run (not skip) on the
disposable ERPNext v16 validation site.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("dashboard",)

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(
    APP_ROOT,
    "synthetic_build_target_app",
    "synthetic_build_target_app",
    "report",
    "owner_daily_business_dashboard",
)
REPORT_JSON_PATH = os.path.join(
    REPORT_DIR, "owner_daily_business_dashboard.json"
)
REPORT_MODULE_DOTTED_PATH = (
    "synthetic_build_target_app.synthetic_build_target_app.report."
    "owner_daily_business_dashboard.owner_daily_business_dashboard"
)

FRAPPE_AVAILABLE = importlib.util.find_spec("frappe") is not None
if FRAPPE_AVAILABLE:
    import frappe
    from frappe.utils import add_days, flt, getdate, nowdate


class TestOwnerDailyBusinessDashboardReportStaticWiring(unittest.TestCase):
    """Structural checks only -- not behavior evidence by themselves."""

    @classmethod
    def setUpClass(cls):
        with open(REPORT_JSON_PATH, "r", encoding="utf-8") as handle:
            cls.definition = json.load(handle)
        report_py_path = os.path.join(
            REPORT_DIR, "owner_daily_business_dashboard.py"
        )
        with open(report_py_path, "r", encoding="utf-8") as handle:
            cls.report_source = handle.read()

    def test_report_is_a_standard_script_report_in_this_module(self):
        self.assertEqual(self.definition["report_type"], "Script Report")
        self.assertEqual(self.definition["is_standard"], "Yes")
        self.assertEqual(self.definition["module"], "Synthetic Build Target App")
        self.assertEqual(
            self.definition["name"], "Owner Daily Business Dashboard"
        )

    def test_report_exposes_company_and_date_filters(self):
        filter_fields = {f["fieldname"] for f in self.definition.get("filters", [])}
        self.assertIn("company", filter_fields)
        self.assertIn("date", filter_fields)

    def test_report_python_defines_execute(self):
        self.assertIn("def execute(filters=None):", self.report_source)

    def test_report_python_computes_all_six_requested_metrics(self):
        for fieldname in (
            "todays_sales",
            "expenses",
            "cash_collected",
            "mobile_money_collected",
            "outstanding_customers",
            "current_profit",
        ):
            self.assertIn(fieldname, self.report_source)


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; authoritative "
    "evidence must come from a real ERPNext v16 site run.",
)
class TestOwnerDailyBusinessDashboardReportFrappeBacked(unittest.TestCase):
    """Authoritative ERPNext v16 behavior evidence for the owner dashboard.

    Seeds real submitted Sales Invoice, Journal Entry, and Payment Entry
    documents for "today" (and one noise document for "yesterday") on a
    real Frappe/ERPNext v16 site, then calls the report's own ``execute``
    function and asserts the exact returned figures -- proving the date
    filter, company filter, and every one of the six requested metrics
    are backed by real live Frappe database reads against the actual
    ERPNext MariaDB-backed site, with no stand-in or substitute database
    and no mocked Frappe API.
    """

    @classmethod
    def setUpClass(cls):
        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()
        frappe.set_user("Administrator")

        cls.module = importlib.import_module(REPORT_MODULE_DOTTED_PATH)
        cls.today = nowdate()
        cls.company = cls._create_company()
        cls.company_currency = frappe.db.get_value(
            "Company", cls.company, "default_currency"
        )
        cls._ensure_fiscal_year(cls.today, cls.company)
        yesterday = add_days(cls.today, -1)
        if getdate(yesterday).year != getdate(cls.today).year:
            cls._ensure_fiscal_year(yesterday, cls.company)
        cls.customer = cls._create_customer()
        cls.item = cls._create_service_item()
        cls.selling_price_list = cls._ensure_selling_price_list()
        cls._ensure_mode_of_payment("Cash")
        cls._ensure_mode_of_payment("Mobile Money")
        cls.debtors_account = frappe.db.get_value(
            "Company", cls.company, "default_receivable_account"
        )
        cls.cash_account = cls._get_leaf_account(cls.company, "Cash", "Asset")
        cls.expense_account = cls._get_leaf_account(
            cls.company, "Expense", "Expense"
        )

    # -- master data helpers -------------------------------------------

    @classmethod
    def _create_company(cls):
        name = "Owner Dashboard Co"
        if frappe.db.exists("Company", name):
            return name
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc(
                {
                    "doctype": "Warehouse Type",
                    "name": "Transit",
                    "warehouse_type": "Transit",
                }
            ).insert(ignore_permissions=True)
        frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": name,
                "abbr": "ODC",
                "default_currency": "USD",
                "country": "India",
            }
        ).insert(ignore_permissions=True)
        return name

    @classmethod
    def _ensure_fiscal_year(cls, date, company):
        """Ensure a real Fiscal Year covers ``date`` for ``company``.

        Prefers reusing/extending an already-existing Fiscal Year that
        genuinely covers ``date`` (whether global or scoped to this
        company). Only when none exists does it insert a brand-new one
        -- and, in that case, deliberately as the *smallest possible*
        single-day range (exactly ``date``) rather than a full calendar
        year. A full calendar-year range can collide with an
        already-existing, non-``date``-covering Fiscal Year left over
        from another authoritative test module on this shared disposable
        site (for example a short/custom-dated Fiscal Year whose end
        date happens to coincide with this calendar year's end date),
        which real ERPNext rejects as an overlap even though that other
        Fiscal Year never actually satisfied the search below. Because
        the search below already proved no existing Fiscal Year covers
        ``date``, a single-day range anchored on ``date`` itself cannot
        overlap any existing Fiscal Year's span either.
        """
        existing = frappe.db.get_list(
            "Fiscal Year",
            filters={
                "year_start_date": ["<=", date],
                "year_end_date": [">=", date],
            },
            fields=["name"],
        )
        for row in existing:
            fy = frappe.get_doc("Fiscal Year", row["name"])
            company_names = [c.company for c in fy.companies]
            if not company_names:
                return fy.name
            if company in company_names:
                return fy.name
            fy.append("companies", {"company": company})
            fy.save(ignore_permissions=True)
            return fy.name

        fy = frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": "Owner Dashboard FY {0}".format(date),
                "year_start_date": date,
                "year_end_date": date,
            }
        )
        fy.append("companies", {"company": company})
        fy.insert(ignore_permissions=True)
        return fy.name

    @classmethod
    def _create_customer(cls):
        name = "Owner Dashboard Customer"
        if frappe.db.exists("Customer", name):
            return name
        group = cls._leaf_customer_group()
        territory = cls._leaf_territory()
        frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": name,
                "customer_type": "Individual",
                "customer_group": group,
                "territory": territory,
                "default_currency": cls.company_currency,
            }
        ).insert(ignore_permissions=True)
        return name

    @classmethod
    def _leaf_customer_group(cls):
        leaves = frappe.db.get_list(
            "Customer Group", filters={"is_group": 0}, fields=["name"], limit=1
        )
        if leaves:
            return leaves[0]["name"]
        roots = frappe.db.get_list(
            "Customer Group", filters={"is_group": 1}, fields=["name"], limit=1
        )
        parent = roots[0]["name"] if roots else None
        doc = frappe.get_doc(
            {
                "doctype": "Customer Group",
                "customer_group_name": "Owner Dashboard Group",
                "is_group": 0,
                "parent_customer_group": parent,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name

    @classmethod
    def _leaf_territory(cls):
        leaves = frappe.db.get_list(
            "Territory", filters={"is_group": 0}, fields=["name"], limit=1
        )
        if leaves:
            return leaves[0]["name"]
        roots = frappe.db.get_list(
            "Territory", filters={"is_group": 1}, fields=["name"], limit=1
        )
        parent = roots[0]["name"] if roots else None
        doc = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": "Owner Dashboard Territory",
                "is_group": 0,
                "parent_territory": parent,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name

    @classmethod
    def _create_service_item(cls):
        name = "Owner Dashboard Service Item"
        if frappe.db.exists("Item", name):
            return name
        uom = cls._ensure_uom("Nos")
        group = cls._leaf_item_group()
        frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": name,
                "item_name": name,
                "item_group": group,
                "stock_uom": uom,
                "is_stock_item": 0,
            }
        ).insert(ignore_permissions=True)
        return name

    @classmethod
    def _ensure_uom(cls, uom_name):
        if not frappe.db.exists("UOM", uom_name):
            frappe.get_doc({"doctype": "UOM", "uom_name": uom_name}).insert(
                ignore_permissions=True
            )
        return uom_name

    @classmethod
    def _leaf_item_group(cls):
        leaves = frappe.db.get_list(
            "Item Group", filters={"is_group": 0}, fields=["name"], limit=1
        )
        if leaves:
            return leaves[0]["name"]
        roots = frappe.db.get_list(
            "Item Group", filters={"is_group": 1}, fields=["name"], limit=1
        )
        if roots:
            parent = roots[0]["name"]
        else:
            parent_doc = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Owner Dashboard Root Group",
                    "is_group": 1,
                }
            )
            parent_doc.insert(ignore_permissions=True)
            parent = parent_doc.name
        doc = frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": "Owner Dashboard Leaf Group",
                "is_group": 0,
                "parent_item_group": parent,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name

    @classmethod
    def _ensure_selling_price_list(cls):
        # ERPNext v16 requires selling_price_list / price_list_currency /
        # plc_conversion_rate on a Sales Invoice. A pristine site may not
        # have a usable selling price list in the company's currency, so
        # create a dedicated one scoped to the test company's currency
        # rather than assuming "Standard Selling" exists with a matching
        # currency.
        name = "Owner Dashboard Selling"
        if frappe.db.exists("Price List", name):
            return name
        frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": name,
                "currency": cls.company_currency,
                "selling": 1,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        return name

    @classmethod
    def _ensure_mode_of_payment(cls, mode_name):
        if not frappe.db.exists("Mode of Payment", mode_name):
            frappe.get_doc(
                {"doctype": "Mode of Payment", "mode_of_payment": mode_name}
            ).insert(ignore_permissions=True)
        return mode_name

    @classmethod
    def _get_leaf_account(cls, company, keyword, root_type):
        rows = frappe.db.get_list(
            "Account",
            filters={
                "company": company,
                "root_type": root_type,
                "is_group": 0,
                "account_name": ["like", "%{0}%".format(keyword)],
            },
            fields=["name"],
            limit=1,
        )
        if rows:
            return rows[0]["name"]
        rows = frappe.db.get_list(
            "Account",
            filters={"company": company, "root_type": root_type, "is_group": 0},
            fields=["name"],
            limit=1,
        )
        return rows[0]["name"]

    # -- transaction helpers ---------------------------------------------

    def _submit_sales_invoice(self, amount, posting_date):
        si = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.customer,
                "company": self.company,
                "currency": self.company_currency,
                "conversion_rate": 1,
                "selling_price_list": self.selling_price_list,
                "price_list_currency": self.company_currency,
                "plc_conversion_rate": 1,
                # Without this flag ERPNext silently resets posting_date
                # (and posting_time) to "today" on save/submit, which
                # would otherwise desynchronize the explicit posting_date
                # below from the due_date set to the same backdated
                # value and incorrectly raise "Due Date cannot be
                # before Posting Date".
                "set_posting_time": 1,
                "posting_date": posting_date,
                "due_date": posting_date,
                "items": [
                    {
                        "item_code": self.item,
                        "qty": 1,
                        "rate": amount,
                    }
                ],
            }
        )
        si.insert(ignore_permissions=True)
        si.submit()
        return si

    def _submit_journal_entry_expense(self, amount, posting_date):
        je = frappe.get_doc(
            {
                "doctype": "Journal Entry",
                "voucher_type": "Journal Entry",
                "company": self.company,
                "posting_date": posting_date,
                "multi_currency": 0,
                "accounts": [
                    {
                        "account": self.expense_account,
                        "debit_in_account_currency": amount,
                        "credit_in_account_currency": 0,
                    },
                    {
                        "account": self.cash_account,
                        "debit_in_account_currency": 0,
                        "credit_in_account_currency": amount,
                    },
                ],
            }
        )
        je.insert(ignore_permissions=True)
        je.submit()
        return je

    def _submit_payment_entry(self, amount, posting_date, mode_of_payment):
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": self.customer,
                "company": self.company,
                "posting_date": posting_date,
                "paid_from": self.debtors_account,
                "paid_to": self.cash_account,
                "paid_from_account_currency": self.company_currency,
                "paid_to_account_currency": self.company_currency,
                "source_exchange_rate": 1,
                "target_exchange_rate": 1,
                "paid_amount": amount,
                "received_amount": amount,
                "mode_of_payment": mode_of_payment,
                "reference_no": "OWNER-DASH-{0}".format(mode_of_payment),
                "reference_date": posting_date,
            }
        )
        pe.insert(ignore_permissions=True)
        pe.submit()
        return pe

    def test_execute_returns_real_seeded_figures_honoring_date_filter(self):
        yesterday = add_days(self.today, -1)

        # Noise on a different date: must not leak into "today"'s figures.
        self._submit_sales_invoice(999, yesterday)

        self._submit_sales_invoice(500, self.today)
        self._submit_sales_invoice(300, self.today)
        self._submit_journal_entry_expense(120, self.today)
        self._submit_payment_entry(200, self.today, "Cash")
        self._submit_payment_entry(75, self.today, "Mobile Money")

        columns, data = self.module.execute(
            {"company": self.company, "date": self.today}
        )
        self.assertEqual(
            {c["fieldname"] for c in columns},
            {
                "todays_sales",
                "expenses",
                "cash_collected",
                "mobile_money_collected",
                "outstanding_customers",
                "current_profit",
            },
        )
        row = data[0]

        self.assertEqual(flt(row["todays_sales"]), 800)
        self.assertEqual(flt(row["expenses"]), 120)
        self.assertEqual(flt(row["cash_collected"]), 200)
        self.assertEqual(flt(row["mobile_money_collected"]), 75)
        self.assertEqual(flt(row["current_profit"]), 680)
        self.assertGreaterEqual(row["outstanding_customers"], 1)

        outstanding_customer_names = frappe.db.get_list(
            "Sales Invoice",
            filters={
                "docstatus": 1,
                "company": self.company,
                "outstanding_amount": [">", 0],
            },
            pluck="customer",
        )
        self.assertIn(self.customer, outstanding_customer_names)

        # The date filter must be honored: switching to "yesterday" must
        # pick up the noise invoice and show zero for today-only metrics.
        _, other_day_data = self.module.execute(
            {"company": self.company, "date": yesterday}
        )
        other_row = other_day_data[0]
        self.assertEqual(flt(other_row["todays_sales"]), 999)
        self.assertEqual(flt(other_row["expenses"]), 0)
        self.assertEqual(flt(other_row["cash_collected"]), 0)
        self.assertEqual(flt(other_row["mobile_money_collected"]), 0)


if __name__ == "__main__":
    unittest.main()
