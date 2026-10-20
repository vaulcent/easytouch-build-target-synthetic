"""Authoritative ERP behavior evidence for the Sales Invoice -> Project automation.

This module must be executed by `bench execute` against a real, disposable
ERPNext v16 validation site (loaded there as a Frappe module, with an active
MariaDB-backed database connection). Locally, in this dependency-free coding
sandbox, Frappe is unavailable, so the ERP-backed cases are skipped via
unittest.skipUnless. After `finish`, the same module is expected to run for
real inside an installed ERPNext site and must execute (not skip) there.

No alternate, lighter-weight database engine is ever accepted as a stand-in
for the real ERPNext database: this module explicitly refuses to run unless
the live connection's configured backend is MariaDB (see
`_require_mariadb_backend`), rather than silently treating any other
connected engine as equivalent evidence. No mocked Frappe/database calls and
no source-text assertions either: every assertion below is a live Frappe
document read against the real database.
"""

import datetime
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('automation',)

try:
    import frappe
    from frappe.utils import nowdate, getdate

    HAS_FRAPPE = True
except Exception:  # pragma: no cover - exercised only in the local sandbox
    HAS_FRAPPE = False


def _require_mariadb_backend():
    """Hard-fail (not skip) unless the active Frappe connection is MariaDB.

    Any other database engine must never be accepted as a substitute for
    the real ERPNext database when gathering ERP behavior evidence.
    """
    configured_backend = str((frappe.conf.get("db_type") if frappe.conf else None) or "mariadb").lower()
    if configured_backend != "mariadb":
        raise RuntimeError(
            "Refusing to accept a non-MariaDB Frappe connection (backend="
            f"{configured_backend!r}) as ERPNext behavior evidence; this "
            "authoritative suite must run against the real MariaDB-backed "
            "ERPNext v16 site."
        )


def _ensure_connected():
    """Reuse an active bench-execute database context, else connect."""
    if not getattr(frappe.local, "db", None):
        frappe.init(site=frappe.local.site)
        frappe.connect()
    _require_mariadb_backend()


def _ensure_warehouse_type_transit():
    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(
            ignore_permissions=True
        )


def _ensure_company():
    existing = frappe.db.get_value("Company", {}, "name")
    if existing:
        return existing

    _ensure_warehouse_type_transit()
    company = frappe.get_doc(
        {
            "doctype": "Company",
            "company_name": "Easytouch SI Test Co",
            "default_currency": "USD",
            "country": "United States",
        }
    )
    company.insert(ignore_permissions=True)
    return company.name


def _ensure_fiscal_year(company):
    today = getdate(nowdate())
    candidates = frappe.get_all(
        "Fiscal Year",
        filters={
            "year_start_date": ["<=", today],
            "year_end_date": [">=", today],
        },
        fields=["name"],
    )
    for candidate in candidates:
        rows = frappe.get_all(
            "Fiscal Year Company",
            filters={"parent": candidate.name, "company": company},
        )
        companies_table = frappe.get_all(
            "Fiscal Year Company", filters={"parent": candidate.name}
        )
        if not companies_table or rows:
            return candidate.name

    year_start = datetime.date(today.year, 1, 1)
    year_end = datetime.date(today.year, 12, 31)
    fiscal_year = frappe.get_doc(
        {
            "doctype": "Fiscal Year",
            "year": f"SI-Test-{today.year}",
            "year_start_date": year_start,
            "year_end_date": year_end,
        }
    )
    fiscal_year.insert(ignore_permissions=True)
    return fiscal_year.name


def _ensure_leaf(doctype, root_field, root_label, leaf_label, parent_field):
    leaf = frappe.db.get_value(doctype, {"is_group": 0}, "name")
    if leaf:
        return leaf

    root = frappe.db.get_value(doctype, {"is_group": 1}, "name")
    if not root:
        root_doc = frappe.get_doc(
            {
                "doctype": doctype,
                root_field: root_label,
                "is_group": 1,
            }
        )
        root_doc.insert(ignore_permissions=True)
        root = root_doc.name

    leaf_doc = frappe.get_doc(
        {
            "doctype": doctype,
            root_field: leaf_label,
            parent_field: root,
            "is_group": 0,
        }
    )
    leaf_doc.insert(ignore_permissions=True)
    return leaf_doc.name


def _ensure_customer_group():
    return _ensure_leaf(
        "Customer Group",
        "customer_group_name",
        "All Customer Groups",
        "SI Test Customer Group",
        "parent_customer_group",
    )


def _ensure_territory():
    return _ensure_leaf(
        "Territory",
        "territory_name",
        "All Territories",
        "SI Test Territory",
        "parent_territory",
    )


def _ensure_item_group():
    return _ensure_leaf(
        "Item Group",
        "item_group_name",
        "All Item Groups",
        "SI Test Item Group",
        "parent_item_group",
    )


def _ensure_uom(uom_name="Nos"):
    """Ensure the given UOM master exists before any Item links to it.

    A pristine ERPNext v16 site is not guaranteed to ship with the "Nos"
    UOM pre-seeded, so this fixture chain must create it explicitly rather
    than assuming it is present (LinkValidationError otherwise).
    """
    if not frappe.db.exists("UOM", uom_name):
        uom = frappe.get_doc(
            {
                "doctype": "UOM",
                "uom_name": uom_name,
                "name": uom_name,
                "must_be_whole_number": 1,
            }
        )
        uom.insert(ignore_permissions=True)
    return uom_name


def _ensure_service_item(item_group):
    item_code = "SI-TEST-SERVICE-ITEM"
    uom = _ensure_uom("Nos")
    if frappe.db.exists("Item", item_code):
        return item_code
    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_code,
            "item_group": item_group,
            "stock_uom": uom,
            "is_stock_item": 0,
        }
    )
    item.insert(ignore_permissions=True)
    return item.name


def _ensure_income_account(company):
    account = frappe.db.get_value(
        "Account",
        {"account_type": "Income Account", "company": company, "is_group": 0},
        "name",
    )
    if account:
        return account
    # Fall back to any non-group income-type account in the company's tree.
    account = frappe.db.get_value(
        "Account",
        {"root_type": "Income", "company": company, "is_group": 0},
        "name",
    )
    return account


def _ensure_receivable_account(company):
    account = frappe.db.get_value(
        "Account",
        {"account_type": "Receivable", "company": company, "is_group": 0},
        "name",
    )
    return account


def _ensure_cost_center(company):
    return frappe.db.get_value(
        "Cost Center", {"company": company, "is_group": 0}, "name"
    )


def _ensure_company_currency(company):
    return frappe.db.get_value("Company", company, "default_currency")


def _ensure_price_list_in_currency(currency):
    """Create (or reuse) a Selling Price List explicitly denominated in
    the given currency.

    A pristine ERPNext v16 site's default "Standard Selling" price list
    may already be fixed to a different currency (e.g. INR) than the
    test Company's currency (e.g. USD). Relying on that default risks
    ERPNext's `validate_conversion_rate` demanding a Currency Exchange
    record between the two currencies. To keep this suite independent of
    any such pre-existing default, a dedicated price list is created (or
    reused) that is guaranteed to already match the transaction currency,
    so no cross-currency conversion is ever required.
    """
    name = f"SI Test Price List {currency}"
    if frappe.db.exists("Price List", name):
        return name
    price_list = frappe.get_doc(
        {
            "doctype": "Price List",
            "price_list_name": name,
            "currency": currency,
            "selling": 1,
            "enabled": 1,
        }
    )
    price_list.insert(ignore_permissions=True)
    return price_list.name


def _make_customer(label, customer_group, territory):
    name = f"SI Test Customer {label}"
    if frappe.db.exists("Customer", name):
        return name
    customer = frappe.get_doc(
        {
            "doctype": "Customer",
            "customer_name": name,
            "customer_group": customer_group,
            "territory": territory,
            "customer_type": "Individual",
        }
    )
    customer.insert(ignore_permissions=True)
    return name


@unittest.skipUnless(HAS_FRAPPE, "Frappe is only available on the real ERPNext validation site")
class TestSalesInvoiceCreatesProject(unittest.TestCase):
    """Real, MariaDB-backed Frappe evidence for the Sales Invoice -> Project automation."""

    @classmethod
    def setUpClass(cls):
        _ensure_connected()
        cls.company = _ensure_company()
        cls.company_currency = _ensure_company_currency(cls.company)
        cls.fiscal_year = _ensure_fiscal_year(cls.company)
        cls.customer_group = _ensure_customer_group()
        cls.territory = _ensure_territory()
        cls.item_group = _ensure_item_group()
        cls.item_code = _ensure_service_item(cls.item_group)
        cls.income_account = _ensure_income_account(cls.company)
        cls.receivable_account = _ensure_receivable_account(cls.company)
        cls.cost_center = _ensure_cost_center(cls.company)
        cls.price_list = _ensure_price_list_in_currency(cls.company_currency)
        cls.created_invoices = []
        cls.created_customers = []
        cls.created_projects = []

    @classmethod
    def tearDownClass(cls):
        # Projects must be removed before their source Sales Invoices.
        for project_name in cls.created_projects:
            if frappe.db.exists("Project", project_name):
                frappe.delete_doc("Project", project_name, force=1, ignore_permissions=True)

        for invoice_name in cls.created_invoices:
            if frappe.db.exists("Sales Invoice", invoice_name):
                si = frappe.get_doc("Sales Invoice", invoice_name)
                if si.docstatus == 1:
                    si.cancel()
                frappe.delete_doc(
                    "Sales Invoice", invoice_name, force=1, ignore_permissions=True
                )

        for customer_name in cls.created_customers:
            if frappe.db.exists("Customer", customer_name):
                frappe.delete_doc(
                    "Customer", customer_name, force=1, ignore_permissions=True
                )

        frappe.db.commit()

    def _make_invoice(self, label):
        customer = _make_customer(label, self.customer_group, self.territory)
        self.__class__.created_customers.append(customer)

        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer,
                "company": self.company,
                "posting_date": nowdate(),
                "due_date": nowdate(),
                "debit_to": self.receivable_account,
                # Pin the transaction's own currency (and the exchange
                # rate between it and itself) explicitly to the test
                # Company's currency, and pin the selling price list used
                # for item-detail lookups to a dedicated price list that
                # is already denominated in that same currency. This
                # avoids ever requiring a Currency Exchange record: there
                # is no currency pair to convert.
                "currency": self.company_currency,
                "conversion_rate": 1,
                "selling_price_list": self.price_list,
                "price_list_currency": self.company_currency,
                "plc_conversion_rate": 1,
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
        invoice.insert(ignore_permissions=True)
        self.__class__.created_invoices.append(invoice.name)
        return invoice

    def test_submitted_invoice_creates_exactly_one_correctly_named_project(self):
        from synthetic_build_target_app.sales_invoice_project import (
            get_project_name_for_invoice,
        )

        invoice_a = self._make_invoice("Alpha")
        invoice_b = self._make_invoice("Beta")

        invoice_a.submit()
        invoice_b.submit()
        frappe.db.commit()

        project_a_name = get_project_name_for_invoice(invoice_a)
        project_b_name = get_project_name_for_invoice(invoice_b)
        self.__class__.created_projects.append(project_a_name)
        self.__class__.created_projects.append(project_b_name)

        self.assertNotEqual(project_a_name, project_b_name)
        self.assertTrue(frappe.db.exists("Project", project_a_name))
        self.assertTrue(frappe.db.exists("Project", project_b_name))

        count_a = frappe.db.count("Project", {"project_name": project_a_name})
        count_b = frappe.db.count("Project", {"project_name": project_b_name})
        self.assertEqual(count_a, 1)
        self.assertEqual(count_b, 1)

        self.assertIn(invoice_a.customer_name or invoice_a.customer, project_a_name)
        self.assertIn(invoice_a.name, project_a_name)
        self.assertIn(invoice_b.customer_name or invoice_b.customer, project_b_name)
        self.assertIn(invoice_b.name, project_b_name)

        # The created Project must carry the mandatory `company` field,
        # correctly scoped to the same Company as its originating
        # Sales Invoice (not merely a non-empty value).
        project_a_company = frappe.db.get_value("Project", project_a_name, "company")
        project_b_company = frappe.db.get_value("Project", project_b_name, "company")
        self.assertEqual(project_a_company, invoice_a.company)
        self.assertEqual(project_b_company, invoice_b.company)
        self.assertEqual(project_a_company, self.company)
        self.assertEqual(project_b_company, self.company)

    def test_draft_invoice_creates_no_project(self):
        from synthetic_build_target_app.sales_invoice_project import (
            get_project_name_for_invoice,
        )

        draft_invoice = self._make_invoice("DraftOnly")
        project_name = get_project_name_for_invoice(draft_invoice)

        self.assertEqual(draft_invoice.docstatus, 0)
        self.assertFalse(frappe.db.exists("Project", project_name))

    def test_repeating_the_submitted_event_creates_no_duplicate(self):
        from synthetic_build_target_app.sales_invoice_project import (
            create_project_for_submitted_sales_invoice,
            get_project_name_for_invoice,
        )

        invoice = self._make_invoice("Retry")
        invoice.submit()
        frappe.db.commit()

        project_name = get_project_name_for_invoice(invoice)
        self.__class__.created_projects.append(project_name)
        self.assertTrue(frappe.db.exists("Project", project_name))
        self.assertEqual(frappe.db.count("Project", {"project_name": project_name}), 1)

        # Simulate the submitted-invoice on_submit event firing again
        # (e.g. an event retry/replay) by re-invoking the exact hook
        # handler registered in hooks.py against the already-submitted
        # document.
        reloaded = frappe.get_doc("Sales Invoice", invoice.name)
        create_project_for_submitted_sales_invoice(reloaded)
        create_project_for_submitted_sales_invoice(reloaded)
        frappe.db.commit()

        self.assertEqual(frappe.db.count("Project", {"project_name": project_name}), 1)
        self.assertEqual(
            frappe.db.get_value("Project", project_name, "company"), invoice.company
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
