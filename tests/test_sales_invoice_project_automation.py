"""Authoritative ERP behavior evidence for the Sales Invoice -> Project
automation.

This module is loaded by `bench execute` against a disposable ERPNext v16
site. It submits real Sales Invoices and asserts the real on_submit hook
(`synthetic_build_target_app.sales_invoice_automation.create_project_from_sales_invoice`)
creates exactly one correctly named Project per submitted invoice, that a
draft invoice creates none, and that repeating the same submitted-invoice
event (hook retry) creates no duplicate.

Locally (no Frappe installed) this module is skipped via skipUnless. On the
real disposable ERPNext v16 validation site it must execute.
"""

import unittest

try:
    import frappe
    from frappe.utils import nowdate

    from synthetic_build_target_app.sales_invoice_automation import (
        create_project_from_sales_invoice,
    )

    FRAPPE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when Frappe is absent
    FRAPPE_AVAILABLE = False

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('automation',)


def _ensure_db_connection():
    if getattr(frappe.local, "db", None):
        return
    frappe.init(site=frappe.local.site)
    frappe.connect()


def _ensure_tree_leaf(doctype, name_field, parent_field):
    """Return the name of a non-group leaf record for a tree DocType,
    preferring an existing leaf and only creating a root + leaf when the
    tree is entirely empty of leaves."""
    existing_leaf = frappe.get_all(doctype, filters={"is_group": 0}, fields=["name"], limit=1)
    if existing_leaf:
        return existing_leaf[0].name

    existing_root = frappe.get_all(
        doctype, filters={parent_field: ["in", ["", None]]}, fields=["name"], limit=1
    )
    if existing_root:
        root_name = existing_root[0].name
    else:
        root_label = f"All {doctype}s Automation Root"
        root_doc = frappe.get_doc(
            {
                "doctype": doctype,
                name_field: root_label,
                parent_field: "",
                "is_group": 1,
            }
        )
        root_doc.insert(ignore_permissions=True)
        root_name = root_doc.name

    leaf_label = f"Automation Test {doctype} {frappe.generate_hash(length=6)}"
    leaf_doc = frappe.get_doc(
        {
            "doctype": doctype,
            name_field: leaf_label,
            parent_field: root_name,
            "is_group": 0,
        }
    )
    leaf_doc.insert(ignore_permissions=True)
    return leaf_doc.name


def _get_or_create_uom():
    rows = frappe.get_all("UOM", filters={"name": "Nos"}, limit=1)
    if rows:
        return rows[0].name
    rows = frappe.get_all("UOM", limit=1)
    if rows:
        return rows[0].name
    doc = frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"})
    doc.insert(ignore_permissions=True)
    return doc.name


def _get_or_create_company():
    existing = frappe.get_all("Company", fields=["name"], limit=1)
    if existing:
        return existing[0].name

    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc(
            {"doctype": "Warehouse Type", "name": "Transit", "warehouse_type": "Transit"}
        ).insert(ignore_permissions=True)

    company_doc = frappe.get_doc(
        {
            "doctype": "Company",
            "company_name": "Automation Test Co",
            "abbr": "ATC",
            "default_currency": "USD",
            "country": "United States",
        }
    )
    company_doc.insert(ignore_permissions=True)
    return company_doc.name


def _ensure_fiscal_year(company):
    today = nowdate()
    fy_name = frappe.db.get_value(
        "Fiscal Year",
        {"year_start_date": ["<=", today], "year_end_date": [">=", today]},
        "name",
    )
    if fy_name:
        fy_doc = frappe.get_doc("Fiscal Year", fy_name)
        company_rows = fy_doc.get("companies") or []
        company_names = [row.company for row in company_rows]
        if company_names and company not in company_names:
            fy_doc.append("companies", {"company": company})
            fy_doc.save(ignore_permissions=True)
        return fy_doc.name

    year = frappe.utils.getdate(today).year
    fy_doc = frappe.get_doc(
        {
            "doctype": "Fiscal Year",
            "year": str(year),
            "year_start_date": f"{year}-01-01",
            "year_end_date": f"{year}-12-31",
        }
    )
    fy_doc.insert(ignore_permissions=True)
    return fy_doc.name


def _get_leaf_account(company, filters):
    account_filters = dict(filters)
    account_filters.update({"company": company, "is_group": 0})
    rows = frappe.get_all("Account", filters=account_filters, fields=["name"], limit=1)
    return rows[0].name if rows else None


def _get_or_create_selling_price_list(currency):
    """Return a selling Price List whose currency matches the given
    currency, preferring an existing one. ERPNext's shipped "Standard
    Selling" fixture Price List may use a currency (historically INR)
    that does not match the test Company's currency; using it unchanged
    forces an unwanted currency conversion on every invoice. Creating or
    selecting a Price List whose currency already matches the Company
    currency avoids the "Exchange Rate is mandatory" validation entirely
    for this automation test, since conversion rate is only required when
    the invoice currency differs from the company currency."""
    rows = frappe.get_all(
        "Price List",
        filters={"selling": 1, "currency": currency},
        fields=["name"],
        limit=1,
    )
    if rows:
        return rows[0].name

    name = f"Automation Selling Price List {currency}"
    if frappe.db.exists("Price List", name):
        doc = frappe.get_doc("Price List", name)
        doc.currency = currency
        doc.selling = 1
        doc.save(ignore_permissions=True)
        return doc.name

    doc = frappe.get_doc(
        {
            "doctype": "Price List",
            "price_list_name": name,
            "currency": currency,
            "selling": 1,
            "enabled": 1,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class TestSalesInvoiceProjectAutomation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_db_connection()

        cls._created_customers = []
        cls._created_invoices = []
        cls._created_projects = []

        cls.company = _get_or_create_company()
        cls.company_currency = frappe.db.get_value("Company", cls.company, "default_currency")
        _ensure_fiscal_year(cls.company)

        cls.customer_group = _ensure_tree_leaf(
            "Customer Group", "customer_group_name", "parent_customer_group"
        )
        cls.territory = _ensure_tree_leaf("Territory", "territory_name", "parent_territory")
        cls.item_group = _ensure_tree_leaf("Item Group", "item_group_name", "parent_item_group")
        cls.uom = _get_or_create_uom()

        cls.item_code = "AUTOMATION-TEST-SERVICE-ITEM"
        if not frappe.db.exists("Item", cls.item_code):
            frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": cls.item_code,
                    "item_name": cls.item_code,
                    "item_group": cls.item_group,
                    "stock_uom": cls.uom,
                    "is_stock_item": 0,
                }
            ).insert(ignore_permissions=True)

        cls.selling_price_list = _get_or_create_selling_price_list(cls.company_currency)

        cls.income_account = _get_leaf_account(cls.company, {"root_type": "Income"})
        cls.debit_to = _get_leaf_account(cls.company, {"account_type": "Receivable"})
        cls.cost_center = frappe.db.get_value("Company", cls.company, "cost_center")
        if not cls.cost_center:
            rows = frappe.get_all(
                "Cost Center", filters={"company": cls.company, "is_group": 0}, limit=1
            )
            cls.cost_center = rows[0].name if rows else None

        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        # Delete Projects linked to the test Sales Invoices before removing
        # the invoices themselves (cancelling/deleting an invoice does not
        # remove a Project created by another on_submit hook).
        for project_name in cls._created_projects:
            if frappe.db.exists("Project", project_name):
                frappe.delete_doc("Project", project_name, force=True, ignore_permissions=True)

        for invoice_name in cls._created_invoices:
            if frappe.db.exists("Sales Invoice", invoice_name):
                inv = frappe.get_doc("Sales Invoice", invoice_name)
                if inv.docstatus == 1:
                    inv.cancel()
                frappe.delete_doc(
                    "Sales Invoice", invoice_name, force=True, ignore_permissions=True
                )

        for customer_name in cls._created_customers:
            if frappe.db.exists("Customer", customer_name):
                frappe.delete_doc(
                    "Customer", customer_name, force=True, ignore_permissions=True
                )

        frappe.db.commit()

    def _make_customer(self, label):
        name = f"{label} {frappe.generate_hash(length=6)}"
        doc = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": name,
                "customer_group": self.customer_group,
                "territory": self.territory,
                "default_currency": self.company_currency,
                "default_price_list": self.selling_price_list,
            }
        )
        doc.insert(ignore_permissions=True)
        self.__class__._created_customers.append(doc.name)
        return doc.name

    def _make_invoice(self, customer, submit):
        item_row = {
            "item_code": self.item_code,
            "qty": 1,
            "rate": 100,
        }
        if self.income_account:
            item_row["income_account"] = self.income_account
        if self.cost_center:
            item_row["cost_center"] = self.cost_center

        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer,
                "company": self.company,
                "currency": self.company_currency,
                "conversion_rate": 1,
                "selling_price_list": self.selling_price_list,
                "price_list_currency": self.company_currency,
                "plc_conversion_rate": 1,
                "due_date": nowdate(),
                "posting_date": nowdate(),
                "set_posting_time": 1,
                "items": [item_row],
            }
        )
        if self.debit_to:
            invoice.debit_to = self.debit_to
        invoice.insert(ignore_permissions=True)
        self.__class__._created_invoices.append(invoice.name)
        if submit:
            invoice.submit()
            frappe.db.commit()
        return invoice

    def test_submitted_invoices_for_different_customers_each_create_one_project(self):
        customer_a = self._make_customer("Automation Customer A")
        customer_b = self._make_customer("Automation Customer B")

        invoice_a = self._make_invoice(customer_a, submit=True)
        invoice_b = self._make_invoice(customer_b, submit=True)

        project_a_name = frappe.db.get_value(
            "Project", {"synthetic_sales_invoice": invoice_a.name}, "name"
        )
        project_b_name = frappe.db.get_value(
            "Project", {"synthetic_sales_invoice": invoice_b.name}, "name"
        )

        self.assertTrue(project_a_name, "Expected a Project linked to invoice A")
        self.assertTrue(project_b_name, "Expected a Project linked to invoice B")
        self.assertNotEqual(project_a_name, project_b_name)

        self.__class__._created_projects.extend([project_a_name, project_b_name])

        customer_a_label = frappe.db.get_value("Customer", customer_a, "customer_name")
        customer_b_label = frappe.db.get_value("Customer", customer_b, "customer_name")

        self.assertEqual(
            frappe.db.get_value("Project", project_a_name, "project_name"),
            f"{customer_a_label} - {invoice_a.name}",
        )
        self.assertEqual(
            frappe.db.get_value("Project", project_b_name, "project_name"),
            f"{customer_b_label} - {invoice_b.name}",
        )

        # Exactly one Project per submitted invoice.
        self.assertEqual(
            frappe.db.count("Project", {"synthetic_sales_invoice": invoice_a.name}), 1
        )
        self.assertEqual(
            frappe.db.count("Project", {"synthetic_sales_invoice": invoice_b.name}), 1
        )

    def test_draft_invoice_creates_no_project(self):
        customer = self._make_customer("Automation Customer Draft")
        invoice = self._make_invoice(customer, submit=False)

        self.assertEqual(invoice.docstatus, 0)
        self.assertEqual(
            frappe.db.count("Project", {"synthetic_sales_invoice": invoice.name}), 0
        )

    def test_repeated_submit_event_creates_no_duplicate_project(self):
        customer = self._make_customer("Automation Customer Retry")
        invoice = self._make_invoice(customer, submit=True)

        project_name = frappe.db.get_value(
            "Project", {"synthetic_sales_invoice": invoice.name}, "name"
        )
        self.assertTrue(project_name)
        self.__class__._created_projects.append(project_name)

        self.assertEqual(
            frappe.db.count("Project", {"synthetic_sales_invoice": invoice.name}), 1
        )

        # Simulate a retried/duplicate on_submit event delivery by invoking
        # the real hook handler again directly against the same submitted
        # invoice document.
        create_project_from_sales_invoice(invoice)
        frappe.db.commit()

        self.assertEqual(
            frappe.db.count("Project", {"synthetic_sales_invoice": invoice.name}), 1
        )
