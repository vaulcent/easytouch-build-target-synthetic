"""Authoritative ERP-backed evidence for the Sales Invoice -> Project
automation.

Loaded by `bench execute` against a disposable, live ERPNext v16 site. It
proves that the real Sales Invoice `on_submit` hook registered by this app
creates exactly one Project, named from the invoice's customer and invoice
number, every time a Sales Invoice is submitted; that a draft invoice
creates none; and that re-firing the same submitted-invoice event does not
create a duplicate.

Lookups for the created Project are always performed via the
``project_name`` field (never by assuming that deterministic string is the
Project's primary ``name``), because ERPNext's Project autoname behaviour
is an internal implementation detail this suite must not assume.

When Frappe is unavailable (the local coding sandbox), the ERP-backed cases
are skipped via unittest.skipUnless; they must execute for real once this
module runs inside an installed ERPNext v16 site.
"""

import unittest

try:
    import frappe

    FRAPPE_AVAILABLE = True
except ImportError:  # pragma: no cover - expected in the local coding sandbox
    FRAPPE_AVAILABLE = False

# Literal marker required by the deterministic completion contract.
EASYTOUCH_ERP_BEHAVIOR_KINDS = ("dashboard", "automation")

APP_NAME = "synthetic_build_target_app"
PREFIX = "EASYTOUCH-SIPA"


def _ensure_frappe_context():
    """Reuse the active bench execute DB context, or connect to the site."""
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


def _ensure_leaf(doctype, name_field, parent_field):
    """Return a non-group leaf record for a hierarchical master, creating one
    under the real tree root if no leaf already exists on this site."""
    leaf = frappe.db.get_value(doctype, {"is_group": 0}, "name")
    if leaf:
        return leaf

    root = frappe.db.get_value(doctype, {"is_group": 1}, "name")
    if not root:
        root = frappe.db.get_value(doctype, {}, "name")

    new_name = f"{PREFIX}-{doctype.upper().replace(' ', '-')}"
    if frappe.db.exists(doctype, new_name):
        return new_name

    doc = frappe.get_doc(
        {
            "doctype": doctype,
            name_field: new_name,
            parent_field: root,
            "is_group": 0,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


def _ensure_warehouse_type_transit():
    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc(
            {"doctype": "Warehouse Type", "name": "Transit", "warehouse_type": "Transit"}
        ).insert(ignore_permissions=True)


def _get_or_create_company():
    existing = frappe.db.get_value("Company", {}, "name")
    if existing:
        return existing

    _ensure_warehouse_type_transit()

    abbr = "ESIP"
    name = f"{PREFIX} Company"
    if frappe.db.exists("Company", name):
        return name

    company = frappe.get_doc(
        {
            "doctype": "Company",
            "company_name": name,
            "abbr": abbr,
            "default_currency": "USD",
            "country": "United States",
            "domain": "Services",
            "chart_of_accounts": "Standard",
        }
    )
    company.insert(ignore_permissions=True)
    return company.name


def _get_company_defaults(company):
    income_account = frappe.db.get_value(
        "Account",
        {"company": company, "root_type": "Income", "is_group": 0},
        "name",
    )
    receivable_account = frappe.db.get_value(
        "Account",
        {"company": company, "account_type": "Receivable", "is_group": 0},
        "name",
    )
    cost_center = frappe.db.get_value(
        "Cost Center", {"company": company, "is_group": 0}, "name"
    )
    return income_account, receivable_account, cost_center


def _ensure_fiscal_year(company, posting_date):
    from frappe.utils import getdate

    rows = frappe.db.sql(
        """
        select name
        from `tabFiscal Year`
        where %(date)s between year_start_date and year_end_date
        """,
        {"date": posting_date},
        as_dict=True,
    )
    for row in rows:
        linked = frappe.get_all(
            "Fiscal Year Company", filters={"parent": row.name}, pluck="company"
        )
        if not linked or company in linked:
            return row.name

    year = getdate(posting_date).year
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    fy_name = f"{PREFIX}-{year}"
    if frappe.db.exists("Fiscal Year", fy_name):
        return fy_name

    fy_doc = frappe.get_doc(
        {
            "doctype": "Fiscal Year",
            "year": fy_name,
            "year_start_date": start,
            "year_end_date": end,
            "companies": [{"company": company}],
        }
    )
    fy_doc.insert(ignore_permissions=True)
    return fy_doc.name


def _ensure_uom():
    if frappe.db.exists("UOM", "Nos"):
        return "Nos"
    existing = frappe.db.get_value("UOM", {}, "name")
    if existing:
        return existing
    frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)
    return "Nos"


def _ensure_item_group_leaf():
    leaf = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
    if leaf:
        return leaf

    root = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
    if not root:
        root_doc = frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": f"{PREFIX}-ROOT-ITEM-GROUP",
                "is_group": 1,
                "parent_item_group": "",
            }
        )
        root_doc.insert(ignore_permissions=True)
        root = root_doc.name

    name = f"{PREFIX}-ITEM-GROUP"
    if frappe.db.exists("Item Group", name):
        return name

    doc = frappe.get_doc(
        {
            "doctype": "Item Group",
            "item_group_name": name,
            "parent_item_group": root,
            "is_group": 0,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


def _ensure_service_item():
    item_code = f"{PREFIX}-SERVICE-ITEM"
    if frappe.db.exists("Item", item_code):
        return item_code

    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_code,
            "item_group": _ensure_item_group_leaf(),
            "stock_uom": _ensure_uom(),
            "is_stock_item": 0,
        }
    )
    item.insert(ignore_permissions=True)
    return item.name


def _ensure_price_list(currency):
    """Return a Selling Price List explicitly scoped to ``currency``.

    ERPNext's fixture-installed "Standard Selling" Price List may carry a
    hardcoded currency (commonly INR) independent of the test Company's
    default currency. Relying on it can trigger a spurious "Exchange Rate
    is mandatory" error when no Currency Exchange record bridges the two
    currencies. Using a dedicated price list in the Company's own currency
    avoids any cross-currency conversion during item pricing lookup.
    """
    name = f"{PREFIX}-PRICE-LIST-{currency}"
    if frappe.db.exists("Price List", name):
        return name

    price_list = frappe.get_doc(
        {
            "doctype": "Price List",
            "price_list_name": name,
            "currency": currency,
            "selling": 1,
            "buying": 0,
            "enabled": 1,
        }
    )
    price_list.insert(ignore_permissions=True)
    return price_list.name


def _make_customer(suffix):
    name = f"{PREFIX}-CUSTOMER-{suffix}"
    if frappe.db.exists("Customer", name):
        frappe.delete_doc("Customer", name, force=1, ignore_permissions=True)

    territory = _ensure_leaf("Territory", "territory_name", "parent_territory")
    customer_group = _ensure_leaf(
        "Customer Group", "customer_group_name", "parent_customer_group"
    )

    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": name,
            "customer_type": "Company",
            "territory": territory,
            "customer_group": customer_group,
        }
    )
    customer.insert(ignore_permissions=True)
    return customer.name


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is unavailable in this local sandbox")
class TestSalesInvoiceProjectAutomationErpBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_frappe_context()
        from frappe.utils import nowdate

        cls.posting_date = nowdate()
        cls.company = _get_or_create_company()
        cls.company_currency = frappe.db.get_value(
            "Company", cls.company, "default_currency"
        )
        cls.income_account, cls.receivable_account, cls.cost_center = (
            _get_company_defaults(cls.company)
        )
        cls.fiscal_year = _ensure_fiscal_year(cls.company, cls.posting_date)
        cls.item_code = _ensure_service_item()
        cls.price_list = _ensure_price_list(cls.company_currency)
        frappe.db.commit()

        cls.created_invoices = []
        cls.created_customers = []

    @classmethod
    def tearDownClass(cls):
        from synthetic_build_target_app.sales_invoice_automation import (
            project_name_for_invoice,
        )

        # Delete Projects created by the hook before removing the source
        # invoices, per the completion contract. Look the Project up by its
        # project_name field value -- never assume that string is the
        # Project's primary document name.
        for inv in cls.created_invoices:
            project_name = project_name_for_invoice(inv)
            project_docname = frappe.db.get_value(
                "Project", {"project_name": project_name}, "name"
            )
            if project_docname:
                frappe.delete_doc(
                    "Project", project_docname, force=1, ignore_permissions=True
                )

        for inv in cls.created_invoices:
            fresh = frappe.get_doc("Sales Invoice", inv.name)
            if fresh.docstatus == 1:
                fresh.cancel()
            frappe.delete_doc(
                "Sales Invoice", inv.name, force=1, ignore_permissions=True
            )

        for customer_name in cls.created_customers:
            if frappe.db.exists("Customer", customer_name):
                frappe.delete_doc(
                    "Customer", customer_name, force=1, ignore_permissions=True
                )

        frappe.db.commit()

    def _new_invoice(self, customer):
        inv = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer,
                "company": self.company,
                "currency": self.company_currency,
                "conversion_rate": 1,
                "selling_price_list": self.price_list,
                "price_list_currency": self.company_currency,
                "plc_conversion_rate": 1,
                "posting_date": self.posting_date,
                "due_date": self.posting_date,
                "set_posting_time": 1,
                "debit_to": self.receivable_account,
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 1,
                        "rate": 100,
                        "income_account": self.income_account,
                        "cost_center": self.cost_center,
                    }
                ],
            }
        )
        inv.insert(ignore_permissions=True)
        self.created_invoices.append(inv)
        return inv

    def test_submitting_two_invoices_for_different_customers_each_create_one_project(
        self,
    ):
        from synthetic_build_target_app.sales_invoice_automation import (
            project_name_for_invoice,
        )

        customer_a = _make_customer("A")
        customer_b = _make_customer("B")
        self.created_customers.extend([customer_a, customer_b])

        invoice_a = self._new_invoice(customer_a)
        invoice_b = self._new_invoice(customer_b)

        invoice_a.submit()
        invoice_b.submit()
        frappe.db.commit()

        expected_name_a = project_name_for_invoice(invoice_a)
        expected_name_b = project_name_for_invoice(invoice_b)

        self.assertIn(invoice_a.customer_name or invoice_a.customer, expected_name_a)
        self.assertIn(invoice_a.name, expected_name_a)
        self.assertIn(invoice_b.customer_name or invoice_b.customer, expected_name_b)
        self.assertIn(invoice_b.name, expected_name_b)

        # Look up the created Project by its project_name field, not by
        # assuming that string is literally the document's primary name.
        self.assertTrue(frappe.db.exists("Project", {"project_name": expected_name_a}))
        self.assertTrue(frappe.db.exists("Project", {"project_name": expected_name_b}))

        project_a_docname = frappe.db.get_value(
            "Project", {"project_name": expected_name_a}, "name"
        )
        project_b_docname = frappe.db.get_value(
            "Project", {"project_name": expected_name_b}, "name"
        )
        project_a = frappe.get_doc("Project", project_a_docname)
        project_b = frappe.get_doc("Project", project_b_docname)
        self.assertEqual(project_a.customer, customer_a)
        self.assertEqual(project_b.customer, customer_b)

        count_a = frappe.db.count("Project", {"project_name": expected_name_a})
        count_b = frappe.db.count("Project", {"project_name": expected_name_b})
        self.assertEqual(count_a, 1)
        self.assertEqual(count_b, 1)

    def test_draft_invoice_creates_no_project(self):
        from synthetic_build_target_app.sales_invoice_automation import (
            project_name_for_invoice,
        )

        customer = _make_customer("DRAFT")
        self.created_customers.append(customer)

        draft_invoice = self._new_invoice(customer)
        self.assertEqual(draft_invoice.docstatus, 0)

        expected_name = project_name_for_invoice(draft_invoice)
        self.assertFalse(
            frappe.db.exists("Project", {"project_name": expected_name})
        )

    def test_repeating_submitted_invoice_event_creates_no_duplicate_project(self):
        from synthetic_build_target_app.sales_invoice_automation import (
            create_project_on_submit,
            project_name_for_invoice,
        )

        customer = _make_customer("RETRY")
        self.created_customers.append(customer)

        invoice = self._new_invoice(customer)
        invoice.submit()
        frappe.db.commit()

        expected_name = project_name_for_invoice(invoice)
        self.assertTrue(frappe.db.exists("Project", {"project_name": expected_name}))

        # Simulate the on_submit event firing again (e.g. a retried event)
        # against the now-submitted document.
        submitted = frappe.get_doc("Sales Invoice", invoice.name)
        create_project_on_submit(submitted)
        create_project_on_submit(submitted)
        frappe.db.commit()

        count = frappe.db.count("Project", {"project_name": expected_name})
        self.assertEqual(
            count,
            1,
            "Retried on_submit events must not create duplicate Projects.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
