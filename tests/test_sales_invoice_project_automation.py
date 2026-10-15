"""Authoritative ERP-behavior evidence for the Sales Invoice -> Project
automation.

Requirement: every time a submitted Sales Invoice is created, automatically
create a Project for that invoice using the customer name and invoice
number. The automation is implemented as the Sales Invoice ``on_submit``
hook registered in synthetic_build_target_app/hooks.py, pointing at
synthetic_build_target_app.sales_invoice_events.create_project_from_sales_invoice.

This module is loaded by `bench execute` with an active Frappe database
context against a real, disposable ERPNext v16 validation site. Frappe is
unavailable in the local coding sandbox, so these cases skipUnless Frappe can
be imported locally; they are not skipped, and must execute, once run inside
an installed ERPNext site.

Lookups below always resolve a Project by its ``project_name`` field value
(never by assuming that value equals the Project's primary ``name``), since
ERPNext's Project doctype naming strategy is site/version dependent.
"""
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('automation',)

try:
    import frappe  # noqa: F401
    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False


def _ensure_connection():
    """Reuse frappe.local.db when present; otherwise connect from
    frappe.local.site (as set up by `bench execute`)."""
    import frappe

    if not getattr(frappe.local, "db", None):
        site = getattr(frappe.local, "site", None)
        frappe.init(site=site)
        frappe.connect()
    frappe.set_user("Administrator")


def _ensure_warehouse_type_transit():
    import frappe

    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc({
            "doctype": "Warehouse Type",
            "name": "Transit",
            "warehouse_type": "Transit",
        }).insert(ignore_permissions=True)


def _get_or_create_company():
    """Return a Company whose default currency is USD.

    A pristine disposable site may already ship a demo Company whose
    default currency is not USD (commonly INR). Blindly reusing *any*
    existing Company risks a currency mismatch between the Sales Invoice
    and the Company that ERPNext cannot resolve without a live Currency
    Exchange rate (which is unavailable/offline in this sandboxed
    validation environment). So this automation test specifically
    requires/creates a USD-currency Company to keep the invoice currency
    and company currency identical, avoiding any exchange-rate lookup.
    """
    import frappe

    usd_companies = frappe.get_all(
        "Company", filters={"default_currency": "USD"}, pluck="name", limit=1,
    )
    if usd_companies:
        return usd_companies[0]

    _ensure_warehouse_type_transit()
    countries = frappe.get_all("Country", pluck="name", limit=1)
    country = countries[0] if countries else "United States"

    abbr = "ATCO"
    suffix = 1
    while frappe.db.exists("Company", {"abbr": abbr}):
        suffix += 1
        abbr = "ATCO{0}".format(suffix)

    company = frappe.get_doc({
        "doctype": "Company",
        "company_name": "Automation Test Co" if abbr == "ATCO" else "Automation Test Co {0}".format(suffix),
        "abbr": abbr,
        "default_currency": "USD",
        "country": country,
    })
    company.insert(ignore_permissions=True)
    return company.name


def _get_or_create_leaf(doctype, name_field, group_field, root_label, leaf_label, parent_field):
    import frappe

    leaves = frappe.get_all(doctype, filters={group_field: 0}, pluck="name", limit=1)
    if leaves:
        return leaves[0]

    roots = frappe.get_all(doctype, filters={group_field: 1}, pluck="name", limit=1)
    if roots:
        root = roots[0]
    else:
        root_doc = frappe.get_doc({
            "doctype": doctype,
            name_field: root_label,
            group_field: 1,
        })
        root_doc.insert(ignore_permissions=True)
        root = root_doc.name

    leaf_doc = frappe.get_doc({
        "doctype": doctype,
        name_field: leaf_label,
        group_field: 0,
        parent_field: root,
    })
    leaf_doc.insert(ignore_permissions=True)
    return leaf_doc.name


def _get_or_create_customer_group():
    return _get_or_create_leaf(
        "Customer Group", "customer_group_name", "is_group",
        "All Customer Groups", "Automation Test Customer Group",
        "parent_customer_group",
    )


def _get_or_create_territory():
    return _get_or_create_leaf(
        "Territory", "territory_name", "is_group",
        "All Territories", "Automation Test Territory",
        "parent_territory",
    )


def _get_or_create_item_group():
    return _get_or_create_leaf(
        "Item Group", "item_group_name", "is_group",
        "All Item Groups", "Automation Test Item Group",
        "parent_item_group",
    )


def _get_or_create_uom():
    import frappe

    uoms = frappe.get_all("UOM", pluck="name", limit=1)
    if uoms:
        return uoms[0]
    uom = frappe.get_doc({"doctype": "UOM", "uom_name": "Automation Test Unit"})
    uom.insert(ignore_permissions=True)
    return uom.name


def _get_or_create_item():
    import frappe

    code = "AUTOMATION-TEST-ITEM"
    if frappe.db.exists("Item", code):
        return code
    item = frappe.get_doc({
        "doctype": "Item",
        "item_code": code,
        "item_name": code,
        "item_group": _get_or_create_item_group(),
        "stock_uom": _get_or_create_uom(),
        "is_stock_item": 0,
    })
    item.insert(ignore_permissions=True)
    return item.name


def _get_or_create_fiscal_year(company):
    import frappe
    from frappe.utils import getdate, nowdate

    today = getdate(nowdate())
    year_start = today.replace(month=1, day=1)
    year_end = today.replace(month=12, day=31)

    candidates = frappe.get_all(
        "Fiscal Year",
        filters=[["year_start_date", "<=", today], ["year_end_date", ">=", today]],
        pluck="name",
    )
    for fy_name in candidates:
        fy = frappe.get_doc("Fiscal Year", fy_name)
        companies = [row.company for row in (fy.companies or [])]
        if not companies or company in companies:
            return fy_name

    fy = frappe.get_doc({
        "doctype": "Fiscal Year",
        "year": "Automation-{0}".format(today.year),
        "year_start_date": year_start,
        "year_end_date": year_end,
    })
    fy.append("companies", {"company": company})
    fy.insert(ignore_permissions=True)
    return fy.name


def _get_income_account(company):
    import frappe

    acc = frappe.db.get_value("Company", company, "default_income_account")
    if acc:
        return acc

    leaves = frappe.get_all(
        "Account",
        filters={"company": company, "root_type": "Income", "is_group": 0},
        pluck="name", limit=1,
    )
    if leaves:
        return leaves[0]

    roots = frappe.get_all(
        "Account",
        filters={"company": company, "root_type": "Income", "is_group": 1},
        pluck="name", limit=1,
    )
    if roots:
        parent = roots[0]
    else:
        root_acc = frappe.get_doc({
            "doctype": "Account",
            "account_name": "Automation Income",
            "is_group": 1,
            "root_type": "Income",
            "company": company,
        })
        root_acc.insert(ignore_permissions=True)
        parent = root_acc.name

    leaf = frappe.get_doc({
        "doctype": "Account",
        "account_name": "Automation Sales Income",
        "is_group": 0,
        "root_type": "Income",
        "account_type": "Income Account",
        "company": company,
        "parent_account": parent,
    })
    leaf.insert(ignore_permissions=True)
    return leaf.name


def _get_cost_center(company):
    import frappe

    cc = frappe.db.get_value("Company", company, "cost_center")
    if cc:
        return cc

    leaves = frappe.get_all(
        "Cost Center", filters={"company": company, "is_group": 0}, pluck="name", limit=1,
    )
    if leaves:
        return leaves[0]

    roots = frappe.get_all(
        "Cost Center", filters={"company": company, "is_group": 1}, pluck="name", limit=1,
    )
    parent = roots[0] if roots else None

    cc_doc = frappe.get_doc({
        "doctype": "Cost Center",
        "cost_center_name": "Automation Test Cost Center",
        "company": company,
        "is_group": 0,
        "parent_cost_center": parent,
    })
    cc_doc.insert(ignore_permissions=True)
    return cc_doc.name


def _get_or_create_customer(customer_name):
    import frappe

    if frappe.db.exists("Customer", {"customer_name": customer_name}):
        return frappe.db.get_value("Customer", {"customer_name": customer_name}, "name")

    customer = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": customer_name,
        "customer_group": _get_or_create_customer_group(),
        "territory": _get_or_create_territory(),
        "customer_type": "Individual",
    })
    customer.insert(ignore_permissions=True)
    return customer.name


def _get_or_create_selling_price_list(currency):
    """Return a selling-enabled Price List whose currency exactly matches
    ``currency``, creating a dedicated one if needed.

    This keeps the Sales Invoice's price-list currency identical to both
    the transaction currency and the Company currency, so ERPNext never
    needs to resolve a Currency Exchange rate during item/price lookups.
    """
    import frappe

    existing = frappe.get_all(
        "Price List",
        filters={"currency": currency, "selling": 1},
        pluck="name", limit=1,
    )
    if existing:
        return existing[0]

    name = "Automation Test Selling Price List {0}".format(currency)
    if frappe.db.exists("Price List", name):
        price_list = frappe.get_doc("Price List", name)
        if not price_list.selling or price_list.currency != currency:
            price_list.selling = 1
            price_list.currency = currency
            price_list.save(ignore_permissions=True)
        return price_list.name

    price_list = frappe.get_doc({
        "doctype": "Price List",
        "price_list_name": name,
        "currency": currency,
        "selling": 1,
        "buying": 0,
        "enabled": 1,
    })
    price_list.insert(ignore_permissions=True)
    return price_list.name


def _make_sales_invoice(customer, company, item_code, income_account, cost_center):
    import frappe
    from frappe.utils import nowdate

    _get_or_create_fiscal_year(company)

    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    price_list = _get_or_create_selling_price_list(company_currency)

    si = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": customer,
        "company": company,
        "currency": company_currency,
        "conversion_rate": 1,
        "selling_price_list": price_list,
        "price_list_currency": company_currency,
        "plc_conversion_rate": 1,
        "posting_date": nowdate(),
        "due_date": nowdate(),
        "items": [{
            "item_code": item_code,
            "qty": 1,
            "rate": 100,
            "income_account": income_account,
            "cost_center": cost_center,
        }],
    })
    si.insert(ignore_permissions=True)
    return si


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class SalesInvoiceProjectAutomationTests(unittest.TestCase):
    """Proves the Sales Invoice on_submit -> Project automation on a real,
    disposable ERPNext v16 site."""

    @classmethod
    def setUpClass(cls):
        _ensure_connection()
        import frappe

        cls.company = _get_or_create_company()
        cls.item_code = _get_or_create_item()
        cls.income_account = _get_income_account(cls.company)
        cls.cost_center = _get_cost_center(cls.company)
        cls.customer_a = _get_or_create_customer("Automation Customer Alpha")
        cls.customer_b = _get_or_create_customer("Automation Customer Beta")

        cls._created_invoices = []
        cls._created_projects = []
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        import frappe

        # Delete Projects linked to test invoices BEFORE touching the
        # invoices, since cancel/delete of a Sales Invoice does not remove
        # a Project created by the on_submit hook.
        for project_doc_name in cls._created_projects:
            if frappe.db.exists("Project", project_doc_name):
                frappe.delete_doc("Project", project_doc_name, force=True, ignore_permissions=True)

        for invoice_name in cls._created_invoices:
            if frappe.db.exists("Sales Invoice", invoice_name):
                si = frappe.get_doc("Sales Invoice", invoice_name)
                if si.docstatus == 1:
                    si.cancel()
                frappe.delete_doc("Sales Invoice", invoice_name, force=True, ignore_permissions=True)

        frappe.db.commit()

    def _track_invoice(self, invoice_name):
        type(self)._created_invoices.append(invoice_name)

    def _track_project_doc_name(self, project_doc_name):
        if project_doc_name:
            type(self)._created_projects.append(project_doc_name)

    def _resolve_project_doc_name(self, project_name_field_value):
        """Look up a Project's actual primary ``name`` by its
        ``project_name`` field value. Never assume the field value equals
        the primary key: ERPNext's Project autoname strategy is
        site/version dependent."""
        import frappe

        return frappe.db.get_value(
            "Project", {"project_name": project_name_field_value}, "name"
        )

    def test_submitted_invoices_each_create_exactly_one_correctly_named_project(self):
        import frappe
        from synthetic_build_target_app.sales_invoice_events import build_project_name

        si_a = _make_sales_invoice(self.customer_a, self.company, self.item_code,
                                    self.income_account, self.cost_center)
        self._track_invoice(si_a.name)
        si_b = _make_sales_invoice(self.customer_b, self.company, self.item_code,
                                    self.income_account, self.cost_center)
        self._track_invoice(si_b.name)

        si_a.submit()
        si_b.submit()
        frappe.db.commit()

        project_name_a = build_project_name(si_a)
        project_name_b = build_project_name(si_b)
        self.assertNotEqual(project_name_a, project_name_b)

        project_a_doc_name = self._resolve_project_doc_name(project_name_a)
        project_b_doc_name = self._resolve_project_doc_name(project_name_b)
        self._track_project_doc_name(project_a_doc_name)
        self._track_project_doc_name(project_b_doc_name)

        self.assertTrue(
            project_a_doc_name,
            "Expected a Project with project_name={0!r} to exist after "
            "submitting Sales Invoice {1}".format(project_name_a, si_a.name),
        )
        self.assertTrue(
            project_b_doc_name,
            "Expected a Project with project_name={0!r} to exist after "
            "submitting Sales Invoice {1}".format(project_name_b, si_b.name),
        )

        self.assertEqual(
            frappe.db.count("Project", {"project_name": project_name_a}), 1,
        )
        self.assertEqual(
            frappe.db.count("Project", {"project_name": project_name_b}), 1,
        )

        project_a = frappe.get_doc("Project", project_a_doc_name)
        self.assertEqual(project_a.project_name, project_name_a)
        self.assertEqual(project_a.customer, self.customer_a)
        self.assertIn(si_a.customer_name or si_a.customer, project_a.project_name)
        self.assertIn(si_a.name, project_a.project_name)

    def test_draft_invoice_creates_no_project(self):
        import frappe
        from synthetic_build_target_app.sales_invoice_events import build_project_name

        si_draft = _make_sales_invoice(self.customer_a, self.company, self.item_code,
                                        self.income_account, self.cost_center)
        self._track_invoice(si_draft.name)
        frappe.db.commit()

        self.assertEqual(si_draft.docstatus, 0)
        draft_project_name = build_project_name(si_draft)
        self.assertFalse(
            frappe.db.exists("Project", {"project_name": draft_project_name})
        )

    def test_repeated_submit_event_does_not_create_duplicate_project(self):
        import frappe
        from synthetic_build_target_app.sales_invoice_events import (
            build_project_name,
            create_project_from_sales_invoice,
        )

        si = _make_sales_invoice(self.customer_b, self.company, self.item_code,
                                  self.income_account, self.cost_center)
        self._track_invoice(si.name)
        si.submit()
        frappe.db.commit()

        project_name = build_project_name(si)
        project_doc_name = self._resolve_project_doc_name(project_name)
        self._track_project_doc_name(project_doc_name)
        self.assertTrue(project_doc_name)
        self.assertEqual(frappe.db.count("Project", {"project_name": project_name}), 1)

        # Simulate the same submitted-invoice on_submit event firing again
        # (e.g. an event retry) and assert no duplicate Project is created.
        create_project_from_sales_invoice(si, method="on_submit")
        create_project_from_sales_invoice(si, method="on_submit")
        frappe.db.commit()

        self.assertEqual(frappe.db.count("Project", {"project_name": project_name}), 1)
        # The resolved primary key must also remain stable across retries.
        self.assertEqual(self._resolve_project_doc_name(project_name), project_doc_name)


if __name__ == "__main__":
    unittest.main()
