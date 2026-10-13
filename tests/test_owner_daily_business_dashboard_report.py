"""Tests for the "Owner Daily Business Dashboard" Script Report.

Requirement: one screen where the owner can see today's sales, expenses,
cash collected, mobile money collected, outstanding customers (names +
real balances), and current profit -- every figure in the selected
Company's base currency.

``TestOwnerDailyBusinessDashboardReportStaticWiring`` runs unconditionally
in this local sandbox (no Frappe) and only checks the report definition's
shape/wiring -- it is NOT behavioral evidence on its own.

``TestOwnerDailyBusinessDashboardReportFrappeBacked`` is the authoritative
behavior evidence: it seeds real submitted ERPNext documents (including a
non-base-currency Sales Invoice with a non-unit exchange rate and a real
partial linked Payment Entry) on a live Frappe/ERPNext v16 site and
executes the report's own ``execute()`` function, comparing every
returned figure against an independently-queried real ERPNext value. It
skips only when Frappe is unavailable in this local coding sandbox; it
must run (not skip) on the disposable ERPNext v16 validation site.

The non-base-currency invoice is deliberately posted for a *separate*
dedicated EUR customer rather than reusing the main (company-currency)
customer: ERPNext enforces, per ``Customer`` + ``Company``, that every
posted GL Entry for a given party uses one consistent account currency
(``erpnext.accounts.party.validate_party_gle_currency``), so a single
customer cannot legitimately carry both a USD-currency invoice and a
EUR-currency invoice against the same Company. Using two distinct real
customers still fully proves the base-currency conversion requirement
(the EUR invoice's own balance must still show up correctly, in base
currency, in both the sales total and the outstanding-customers list)
without fighting that real ERPNext constraint.
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

    def test_report_requires_company_filter_for_base_currency_correctness(self):
        filters_by_fieldname = {
            f["fieldname"]: f for f in self.definition.get("filters", [])
        }
        self.assertIn("company", filters_by_fieldname)
        self.assertIn("date", filters_by_fieldname)
        company_filter = filters_by_fieldname["company"]
        self.assertTrue(
            company_filter.get("mandatory") or company_filter.get("reqd"),
            "Company filter must be mandatory: base-currency figures are "
            "only meaningful for one Company at a time.",
        )

    def test_report_python_defines_execute(self):
        self.assertIn("def execute(filters=None):", self.report_source)

    def test_report_python_uses_base_currency_fields_not_raw_transaction_fields(
        self,
    ):
        self.assertIn("base_grand_total", self.report_source)
        self.assertIn("base_paid_amount", self.report_source)
        self.assertIn("Payment Ledger Entry", self.report_source)

    def test_report_python_identifies_real_mobile_money_modes_of_payment(self):
        self.assertIn("EVC Plus", self.report_source)
        self.assertIn("Zaad", self.report_source)
        self.assertIn("eDahab", self.report_source)

    def test_report_python_computes_outstanding_customer_names_and_amounts(
        self,
    ):
        for fieldname in ("customer", "customer_name", "outstanding_amount"):
            self.assertIn(fieldname, self.report_source)

    def test_report_python_computes_profit_from_gl_income_and_expense(self):
        self.assertIn('"Income"', self.report_source)
        self.assertIn('"Expense"', self.report_source)
        self.assertIn("current_profit", self.report_source)


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; authoritative "
    "evidence must come from a real ERPNext v16 site run.",
)
class TestOwnerDailyBusinessDashboardReportFrappeBacked(unittest.TestCase):
    """Authoritative ERPNext v16 behavior evidence for the owner dashboard."""

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
        cls.customer = cls._create_customer(
            "Owner Dashboard Customer", cls.company_currency
        )
        # A second, dedicated customer used only for the non-base-currency
        # invoice: ERPNext requires one consistent GL account currency per
        # Customer+Company, so the base-currency-conversion proof cannot
        # share the same customer as the company-currency invoices.
        cls.eur_customer = cls._create_customer(
            "Owner Dashboard EUR Customer", "EUR"
        )
        cls.item = cls._create_service_item()
        cls.selling_price_list = cls._ensure_selling_price_list(
            "Owner Dashboard Selling", cls.company_currency
        )
        cls._ensure_currency("EUR")
        cls.eur_selling_price_list = cls._ensure_selling_price_list(
            "Owner Dashboard Selling EUR", "EUR"
        )
        cls._ensure_mode_of_payment("Cash")
        for mode in cls.module.MOBILE_MONEY_MODES_OF_PAYMENT:
            cls._ensure_mode_of_payment(mode)

        cls.debtors_account = frappe.db.get_value(
            "Company", cls.company, "default_receivable_account"
        )
        cls.cash_account = cls._get_leaf_account(cls.company, "Cash", "Asset")
        cls.expense_account = cls._get_leaf_account(
            cls.company, "Expense", "Expense"
        )
        cls.eur_debtors_account = cls._ensure_eur_debtors_account()

        cls.created_sales_invoices = []
        cls.created_journal_entries = []
        cls.created_payment_entries = []

    @classmethod
    def tearDownClass(cls):
        # Reverse creation order: Payment Entries reference Sales
        # Invoices; Projects are hook-created side effects of Sales
        # Invoice submission and must be removed before the invoices
        # themselves (deleting/cancelling an invoice does not remove the
        # Project another on_submit hook created for it).
        for pe_name in reversed(cls.created_payment_entries):
            doc = frappe.get_doc("Payment Entry", pe_name)
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc("Payment Entry", pe_name, force=1)

        for je_name in reversed(cls.created_journal_entries):
            doc = frappe.get_doc("Journal Entry", je_name)
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc("Journal Entry", je_name, force=1)

        for si_name in reversed(cls.created_sales_invoices):
            project_name = frappe.db.get_value(
                "Project", {"sales_invoice": si_name}, "name"
            )
            if project_name:
                frappe.delete_doc("Project", project_name, force=1)
            doc = frappe.get_doc("Sales Invoice", si_name)
            if doc.docstatus == 1:
                doc.cancel()
            frappe.delete_doc("Sales Invoice", si_name, force=1)

        frappe.db.commit()

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
    def _create_customer(cls, name, default_currency):
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
                "default_currency": default_currency,
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
    def _ensure_selling_price_list(cls, name, currency):
        if frappe.db.exists("Price List", name):
            return name
        frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": name,
                "currency": currency,
                "selling": 1,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        return name

    @classmethod
    def _ensure_currency(cls, currency_code):
        if frappe.db.exists("Currency", currency_code):
            if not frappe.db.get_value("Currency", currency_code, "enabled"):
                frappe.db.set_value("Currency", currency_code, "enabled", 1)
            return currency_code
        frappe.get_doc(
            {
                "doctype": "Currency",
                "currency_name": currency_code,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
        return currency_code

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

    @classmethod
    def _ensure_eur_debtors_account(cls):
        """A real, non-group Receivable Account whose own currency is EUR.

        Used as the ``debit_to`` of the EUR Sales Invoice and as the
        ``paid_from`` of the Payment Entry made against it, so that
        Payment Entry's ``source_exchange_rate`` (and therefore
        ``base_paid_amount``) is genuinely non-unit -- proving the report
        must read ``base_paid_amount``/``base_grand_total`` rather than
        the raw transaction-currency ``paid_amount``/``grand_total``.
        """
        name = "Owner Dashboard EUR Debtors"
        existing = frappe.db.get_list(
            "Account",
            filters={"company": cls.company, "account_name": name},
            fields=["name"],
            limit=1,
        )
        if existing:
            return existing[0]["name"]
        parent_account = frappe.db.get_value(
            "Account", cls.debtors_account, "parent_account"
        )
        doc = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": name,
                "company": cls.company,
                "parent_account": parent_account,
                "account_type": "Receivable",
                "account_currency": "EUR",
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name

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
                "set_posting_time": 1,
                "posting_date": posting_date,
                "due_date": posting_date,
                "items": [
                    {"item_code": self.item, "qty": 1, "rate": amount},
                ],
            }
        )
        si.insert(ignore_permissions=True)
        self.created_sales_invoices.append(si.name)
        si.submit()
        return si

    def _submit_foreign_currency_sales_invoice(
        self, amount_eur, conversion_rate, posting_date
    ):
        """A real EUR Sales Invoice, for the dedicated EUR customer,
        posted to a genuinely EUR-currency Receivable account, at a
        deliberately non-unit conversion_rate.
        """
        si = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.eur_customer,
                "company": self.company,
                "currency": "EUR",
                "conversion_rate": conversion_rate,
                "debit_to": self.eur_debtors_account,
                "party_account_currency": "EUR",
                "selling_price_list": self.eur_selling_price_list,
                "price_list_currency": "EUR",
                "plc_conversion_rate": 1,
                "set_posting_time": 1,
                "posting_date": posting_date,
                "due_date": posting_date,
                "items": [
                    {"item_code": self.item, "qty": 1, "rate": amount_eur},
                ],
            }
        )
        si.insert(ignore_permissions=True)
        self.created_sales_invoices.append(si.name)
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
        self.created_journal_entries.append(je.name)
        je.submit()
        return je

    def _submit_payment_entry(self, invoice, mode_of_payment, paid_amount, posting_date):
        """A real submitted ``Payment Entry`` (``Receive``) allocated
        against ``invoice``, in the invoice's own document currency, so
        a foreign-currency invoice produces a genuinely non-unit
        ``source_exchange_rate`` and therefore a non-trivial
        ``base_paid_amount``.
        """
        party_account_currency = invoice.currency
        if party_account_currency == self.company_currency:
            source_exchange_rate = 1
        else:
            source_exchange_rate = flt(invoice.conversion_rate)
        base_paid_amount = flt(paid_amount) * flt(source_exchange_rate)

        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "company": self.company,
                "posting_date": posting_date,
                "party_type": "Customer",
                "party": invoice.customer,
                "mode_of_payment": mode_of_payment,
                "paid_from": invoice.debit_to,
                "paid_from_account_currency": party_account_currency,
                "paid_to": self.cash_account,
                "paid_to_account_currency": self.company_currency,
                "source_exchange_rate": source_exchange_rate,
                "target_exchange_rate": 1,
                "paid_amount": paid_amount,
                "received_amount": base_paid_amount,
                "references": [
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": invoice.name,
                        "allocated_amount": paid_amount,
                    }
                ],
            }
        )
        pe.insert(ignore_permissions=True)
        self.created_payment_entries.append(pe.name)
        pe.submit()
        return pe

    # -- the authoritative behavior test ---------------------------------

    def test_execute_returns_real_seeded_figures_in_base_currency(self):
        yesterday = add_days(self.today, -1)

        # Sales: one company-currency invoice + one non-base-currency
        # (EUR, non-unit exchange rate) invoice, both posted today; plus
        # a company-currency invoice posted *yesterday* that must be
        # excluded from "today"'s figures.
        today_invoice = self._submit_sales_invoice(500, self.today)
        self._submit_sales_invoice(77, yesterday)

        eur_rate = 1.25
        eur_invoice = self._submit_foreign_currency_sales_invoice(
            100, eur_rate, self.today
        )

        # Cash collected today: a partial payment on the company-currency
        # invoice through the real "Cash" Mode of Payment.
        self._submit_payment_entry(today_invoice, "Cash", 200, self.today)

        # Mobile money collected today: a payment through each real
        # mobile-money Mode of Payment master (EVC Plus / Zaad / eDahab).
        mobile_money_amount_each = 50
        for mode in self.module.MOBILE_MONEY_MODES_OF_PAYMENT:
            self._submit_payment_entry(
                today_invoice, mode, mobile_money_amount_each, self.today
            )

        # A real partial payment on the EUR invoice (in EUR, posted
        # today) so base_paid_amount is a genuinely non-unit-rate
        # conversion, and the EUR customer is left with a real open
        # balance in base currency.
        self._submit_payment_entry(eur_invoice, "Cash", 40, self.today)

        # An expense posted today.
        expense_amount = 150
        self._submit_journal_entry_expense(expense_amount, self.today)

        frappe.db.commit()

        _columns, data, _message, _chart, report_summary = self.module.execute(
            {"company": self.company, "date": self.today}
        )
        summary_by_fieldname = {
            card["fieldname"]: card["value"] for card in report_summary
        }

        # -- Independent verification: Today's Sales (base currency).
        expected_sales = frappe.db.sql(
            "select coalesce(sum(base_grand_total), 0) from `tabSales Invoice` "
            "where docstatus = 1 and posting_date = %s and company = %s",
            (self.today, self.company),
        )[0][0]
        self.assertAlmostEqual(
            flt(summary_by_fieldname["todays_sales"]), flt(expected_sales), places=2
        )

        # -- Independent verification: Expenses (real GL Entry rows
        # against Expense-root-type accounts, joined to Account).
        expected_expenses = frappe.db.sql(
            "select coalesce(sum(gle.debit), 0) - coalesce(sum(gle.credit), 0) "
            "from `tabGL Entry` gle inner join `tabAccount` acc "
            "on acc.name = gle.account "
            "where gle.is_cancelled = 0 and gle.posting_date = %s "
            "and gle.company = %s and acc.root_type = 'Expense'",
            (self.today, self.company),
        )[0][0]
        self.assertAlmostEqual(
            flt(summary_by_fieldname["expenses"]), flt(expected_expenses), places=2
        )

        # -- Independent verification: Cash Collected.
        expected_cash = frappe.db.sql(
            "select coalesce(sum(base_paid_amount), 0) from `tabPayment Entry` "
            "where docstatus = 1 and payment_type = 'Receive' "
            "and posting_date = %s and company = %s and mode_of_payment = 'Cash'",
            (self.today, self.company),
        )[0][0]
        self.assertAlmostEqual(
            flt(summary_by_fieldname["cash_collected"]), flt(expected_cash), places=2
        )

        # -- Independent verification: Mobile Money Collected (real
        # EVC Plus / Zaad / eDahab modes, not an assumed "Mobile Money").
        expected_mobile_money = frappe.db.sql(
            "select coalesce(sum(base_paid_amount), 0) from `tabPayment Entry` "
            "where docstatus = 1 and payment_type = 'Receive' "
            "and posting_date = %s and company = %s and mode_of_payment in %s",
            (
                self.today,
                self.company,
                tuple(self.module.MOBILE_MONEY_MODES_OF_PAYMENT),
            ),
        )[0][0]
        self.assertAlmostEqual(
            flt(summary_by_fieldname["mobile_money_collected"]),
            flt(expected_mobile_money),
            places=2,
        )
        self.assertAlmostEqual(
            flt(expected_mobile_money),
            mobile_money_amount_each * len(self.module.MOBILE_MONEY_MODES_OF_PAYMENT),
            places=2,
        )

        # -- Independent verification: Outstanding Customers -- real
        # names + real base-currency balances from Payment Ledger Entry.
        expected_rows = frappe.db.sql(
            "select party, coalesce(sum(amount), 0) as balance "
            "from `tabPayment Ledger Entry` where party_type = 'Customer' "
            "and company = %s and delinked = 0 group by party",
            (self.company,),
            as_dict=True,
        )
        expected_outstanding = {
            row["party"]: flt(row["balance"])
            for row in expected_rows
            if flt(row["balance"]) > self.module.OUTSTANDING_BALANCE_EPSILON
        }
        actual_outstanding = {
            row["customer"]: flt(row["outstanding_amount"]) for row in data
        }
        self.assertEqual(set(actual_outstanding), set(expected_outstanding))
        for customer, amount in expected_outstanding.items():
            self.assertAlmostEqual(actual_outstanding[customer], amount, places=2)
        self.assertIn(self.customer, actual_outstanding)
        self.assertIn(self.eur_customer, actual_outstanding)
        for row in data:
            self.assertEqual(
                row["customer_name"],
                frappe.db.get_value("Customer", row["customer"], "customer_name"),
            )

        expected_outstanding_total = sum(expected_outstanding.values())
        self.assertAlmostEqual(
            flt(summary_by_fieldname["outstanding_customers_total"]),
            flt(expected_outstanding_total),
            places=2,
        )

        # -- Independent verification: Current Profit = Income
        # (credit - debit) - Expense (debit - credit), real GL Entry
        # rows joined to Account.root_type, for the filtered date.
        expected_income = frappe.db.sql(
            "select coalesce(sum(gle.credit), 0) - coalesce(sum(gle.debit), 0) "
            "from `tabGL Entry` gle inner join `tabAccount` acc "
            "on acc.name = gle.account "
            "where gle.is_cancelled = 0 and gle.posting_date = %s "
            "and gle.company = %s and acc.root_type = 'Income'",
            (self.today, self.company),
        )[0][0]
        expected_profit = flt(expected_income) - flt(expected_expenses)
        self.assertAlmostEqual(
            flt(summary_by_fieldname["current_profit"]),
            flt(expected_profit),
            places=2,
        )
