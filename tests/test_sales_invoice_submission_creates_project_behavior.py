"""Authoritative ERPNext v16 behavior evidence for the "every submitted
Sales Invoice automatically creates a Project" requirement.

Proves, against a real disposable ERPNext v16 site, that actually
submitting a real Sales Invoice document:

1. Creates a real Project document named from that invoice's real
   customer name and invoice number.
2. Idempotently links that Project back to its originating Sales Invoice
   via the real "sales_invoice" Custom Field on Project (proving the
   Custom Field actually exists on the live DocType after fixture
   import, not merely in the fixture file).
3. Re-running the same on_submit hook handler for the same already-linked
   invoice does not create a second Project (idempotency).

Loaded by ``bench execute`` with an active Frappe database context:
reuses ``frappe.local.db`` when already present, and only initializes
from ``frappe.local.site`` when needed. Skips only when Frappe itself is
unavailable in this local coding sandbox.
"""

from __future__ import annotations

import importlib.util
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("automation",)

FRAPPE_AVAILABLE = importlib.util.find_spec("frappe") is not None


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; this authoritative "
    "case must run inside a real disposable ERPNext v16 site via "
    "bench execute.",
)
class TestSalesInvoiceSubmissionCreatesProjectBehavior(unittest.TestCase):
    CUSTOMER_NAME = "Easytouch Sales Invoice Project Behavior Test Customer"
    ITEM_CODE = "EASYTOUCH-SALES-INVOICE-PROJECT-TEST-SERVICE"
    PRICE_LIST_NAME = "Easytouch SI Project Test Price List"

    @classmethod
    def setUpClass(cls):
        import frappe

        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        cls.frappe = frappe
        frappe.set_user("Administrator")

        cls.company = cls._ensure_company()
        cls.company_currency = frappe.db.get_value(
            "Company", cls.company, "default_currency"
        )
        cls._ensure_fiscal_year(cls.company)
        cls.customer_group = cls._ensure_leaf_customer_group()
        cls.territory = cls._ensure_leaf_territory()
        cls.customer = cls._ensure_customer()
        cls.income_account = cls._ensure_income_account(cls.company)
        cls.item_code = cls._ensure_service_item()
        # A dedicated selling Price List whose currency exactly matches
        # this test's Company currency (which may be an already-existing
        # company reused from another test module, so it cannot be
        # assumed to be USD). This guarantees the Sales Invoice's own
        # currency and its selling price list currency both equal the
        # Company currency with a 1:1 conversion rate, so no Currency
        # Exchange record is ever required regardless of the site's
        # global default currency or the default "Standard Selling"
        # price list's currency.
        cls.price_list = cls._ensure_price_list(cls.company_currency)

    # -- master-data setup -------------------------------------------------

    @classmethod
    def _ensure_company(cls):
        frappe = cls.frappe
        existing = frappe.get_all("Company", pluck="name", limit=1)
        if existing:
            return existing[0]
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc(
                {
                    "doctype": "Warehouse Type",
                    "name": "Transit",
                    "warehouse_type": "Transit",
                }
            ).insert(ignore_permissions=True)
        company = frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": "Easytouch Sales Invoice Project Test Co",
                "abbr": "ESIPT",
                "default_currency": "USD",
                "country": "United States",
            }
        )
        company.insert(ignore_permissions=True)
        frappe.db.commit()
        return company.name

    @classmethod
    def _ensure_price_list(cls, currency):
        frappe = cls.frappe
        name = cls.PRICE_LIST_NAME
        if frappe.db.exists("Price List", name):
            pl = frappe.get_doc("Price List", name)
            if pl.currency != currency or not pl.selling or not pl.enabled:
                pl.currency = currency
                pl.selling = 1
                pl.enabled = 1
                pl.save(ignore_permissions=True)
            return pl.name
        pl = frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": name,
                "currency": currency,
                "selling": 1,
                "enabled": 1,
            }
        )
        pl.insert(ignore_permissions=True)
        return pl.name

    @classmethod
    def _ensure_fiscal_year(cls, company):
        frappe = cls.frappe
        today = frappe.utils.nowdate()
        year = frappe.utils.getdate(today).year
        start = "%d-01-01" % year
        end = "%d-12-31" % year

        candidates = frappe.get_all(
            "Fiscal Year",
            filters=[
                ["year_start_date", "<=", today],
                ["year_end_date", ">=", today],
            ],
            pluck="name",
        )
        for fy_name in candidates:
            fy = frappe.get_doc("Fiscal Year", fy_name)
            companies = [row.company for row in (fy.companies or [])]
            if not companies:
                return fy_name
            if company in companies:
                return fy_name
            fy.append("companies", {"company": company})
            fy.save(ignore_permissions=True)
            return fy_name

        fy = frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": "Easytouch SI Project Test FY %d" % year,
                "year_start_date": start,
                "year_end_date": end,
            }
        )
        fy.append("companies", {"company": company})
        fy.insert(ignore_permissions=True)
        return fy.name

    @classmethod
    def _ensure_leaf_customer_group(cls):
        frappe = cls.frappe
        leaf = frappe.get_all(
            "Customer Group", filters={"is_group": 0}, pluck="name", limit=1
        )
        if leaf:
            return leaf[0]
        root = frappe.get_all(
            "Customer Group", filters={"is_group": 1}, pluck="name", limit=1
        )
        if root:
            root_name = root[0]
        else:
            root_doc = frappe.get_doc(
                {
                    "doctype": "Customer Group",
                    "customer_group_name": "All Customer Groups",
                    "is_group": 1,
                }
            )
            root_doc.insert(ignore_permissions=True)
            root_name = root_doc.name
        leaf_doc = frappe.get_doc(
            {
                "doctype": "Customer Group",
                "customer_group_name": "Easytouch SI Project Test Group",
                "is_group": 0,
                "parent_customer_group": root_name,
            }
        )
        leaf_doc.insert(ignore_permissions=True)
        return leaf_doc.name

    @classmethod
    def _ensure_leaf_territory(cls):
        frappe = cls.frappe
        leaf = frappe.get_all(
            "Territory", filters={"is_group": 0}, pluck="name", limit=1
        )
        if leaf:
            return leaf[0]
        root = frappe.get_all(
            "Territory", filters={"is_group": 1}, pluck="name", limit=1
        )
        if root:
            root_name = root[0]
        else:
            root_doc = frappe.get_doc(
                {
                    "doctype": "Territory",
                    "territory_name": "All Territories",
                    "is_group": 1,
                }
            )
            root_doc.insert(ignore_permissions=True)
            root_name = root_doc.name
        leaf_doc = frappe.get_doc(
            {
                "doctype": "Territory",
                "territory_name": "Easytouch SI Project Test Territory",
                "is_group": 0,
                "parent_territory": root_name,
            }
        )
        leaf_doc.insert(ignore_permissions=True)
        return leaf_doc.name

    @classmethod
    def _ensure_customer(cls):
        frappe = cls.frappe
        if frappe.db.exists("Customer", cls.CUSTOMER_NAME):
            return cls.CUSTOMER_NAME
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": cls.CUSTOMER_NAME,
                "customer_group": cls.customer_group,
                "territory": cls.territory,
                "customer_type": "Individual",
            }
        )
        customer.insert(ignore_permissions=True)
        return customer.name

    @classmethod
    def _ensure_income_account(cls, company):
        frappe = cls.frappe
        default_income_account = frappe.db.get_value(
            "Company", company, "default_income_account"
        )
        if default_income_account:
            return default_income_account
        accounts = frappe.get_all(
            "Account",
            filters={"company": company, "root_type": "Income", "is_group": 0},
            pluck="name",
            limit=1,
        )
        if accounts:
            return accounts[0]
        parent = frappe.get_all(
            "Account",
            filters={"company": company, "root_type": "Income", "is_group": 1},
            pluck="name",
            limit=1,
        )
        parent_account = parent[0] if parent else None
        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": "Easytouch SI Project Test Sales",
                "company": company,
                "root_type": "Income",
                "account_type": "Income Account",
                "parent_account": parent_account,
                "is_group": 0,
            }
        )
        account.insert(ignore_permissions=True)
        return account.name

    @classmethod
    def _ensure_service_item(cls):
        frappe = cls.frappe
        code = cls.ITEM_CODE
        if frappe.db.exists("Item", code):
            return code
        item_group = frappe.get_all(
            "Item Group", filters={"is_group": 0}, pluck="name", limit=1
        )
        if item_group:
            item_group_name = item_group[0]
        else:
            root = frappe.get_all(
                "Item Group", filters={"is_group": 1}, pluck="name", limit=1
            )
            root_name = (
                root[0]
                if root
                else frappe.get_doc(
                    {
                        "doctype": "Item Group",
                        "item_group_name": "All Item Groups",
                        "is_group": 1,
                    }
                ).insert(ignore_permissions=True).name
            )
            leaf_doc = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Easytouch SI Project Test Items",
                    "is_group": 0,
                    "parent_item_group": root_name,
                }
            )
            leaf_doc.insert(ignore_permissions=True)
            item_group_name = leaf_doc.name
        if not frappe.db.exists("UOM", "Nos"):
            frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(
                ignore_permissions=True
            )
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": code,
                "item_name": code,
                "item_group": item_group_name,
                "stock_uom": "Nos",
                "is_stock_item": 0,
            }
        )
        item.insert(ignore_permissions=True)
        return item.name

    def _make_sales_invoice(self):
        frappe = self.frappe
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.customer,
                "company": self.company,
                "currency": self.company_currency,
                "conversion_rate": 1,
                "selling_price_list": self.price_list,
                "price_list_currency": self.company_currency,
                "plc_conversion_rate": 1,
                "posting_date": frappe.utils.nowdate(),
                "due_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 1,
                        "rate": 100,
                        "income_account": self.income_account,
                    }
                ],
            }
        )
        invoice.insert(ignore_permissions=True)
        invoice.submit()
        self.frappe.db.commit()
        return invoice

    # -- behavior test ------------------------------------------------------

    def test_submitting_sales_invoice_creates_linked_project_idempotently(self):
        frappe = self.frappe

        invoice = self._make_sales_invoice()

        project_name = frappe.db.get_value(
            "Project", {"sales_invoice": invoice.name}, "name"
        )
        self.assertIsNotNone(
            project_name,
            "submitting the Sales Invoice must create a real Project "
            "linked to it via the 'sales_invoice' Custom Field",
        )

        project = frappe.get_doc("Project", project_name)
        self.assertIn(self.CUSTOMER_NAME, project.project_name)
        self.assertIn(invoice.name, project.project_name)
        self.assertEqual(project.sales_invoice, invoice.name)

        # Idempotency: re-running the real hook handler for the same,
        # already-linked invoice must not create a second Project.
        from synthetic_build_target_app.synthetic_build_target_app import (
            sales_invoice_project,
        )

        sales_invoice_project.create_project_for_submitted_sales_invoice(invoice)

        project_count = frappe.db.count(
            "Project", {"sales_invoice": invoice.name}
        )
        self.assertEqual(
            project_count,
            1,
            "re-running the hook for an already-linked invoice must not "
            "create a duplicate Project",
        )


if __name__ == "__main__":
    unittest.main()
