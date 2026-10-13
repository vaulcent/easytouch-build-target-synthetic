"""Authoritative ERP-backed evidence for the "Important Item" low-stock
alert automation.

Loaded by `bench execute` against a disposable, live ERPNext v16 site. It
proves that the real lifecycle hooks registered by this app on every
source transaction that changes Bin quantities -- Sales Invoice (with
update_stock), Delivery Note, Purchase Receipt, Purchase Invoice (with
update_stock), Stock Entry, and Stock Reconciliation -- create a
Notification Log for an enabled Purchase Manager recipient whenever a
Bin's actual_qty for an item marked ``important_item`` drops below the
10-unit threshold; that an otherwise-identical unmarked item never alerts;
that a Sales Invoice without ``update_stock`` never queues a false alert
even though it never touches a Bin; and that cancelling a stock-changing
transaction recalculates the reversed quantity and is itself observed via
the same mechanism.

Every transaction below explicitly pins its own currency, conversion
rate, and a dedicated Price List scoped to the test Company's own
currency. ERPNext's fixture-installed "Standard Buying"/"Standard
Selling" Price Lists can carry a hardcoded currency independent of the
test Company's default currency; relying on them can make
``get_item_details`` silently adopt that foreign currency and then throw
"Exchange Rate is mandatory" because no Currency Exchange record bridges
the two currencies. A dedicated, correctly-scoped Price List on every
transaction avoids any cross-currency conversion during item pricing
lookup.

When Frappe is unavailable (the local coding sandbox), the ERP-backed
cases are skipped via unittest.skipUnless; they must execute for real once
this module runs inside an installed ERPNext v16 site.
"""

import unittest

try:
    import frappe

    FRAPPE_AVAILABLE = True
except ImportError:  # pragma: no cover - expected in the local coding sandbox
    FRAPPE_AVAILABLE = False

# Literal marker required by the deterministic completion contract.
EASYTOUCH_ERP_BEHAVIOR_KINDS = ("dashboard", "automation")

PREFIX = "EASYTOUCH-LSA"
LOW_STOCK_THRESHOLD = 10


class _DotDict(dict):
    """Minimal attribute-and-.get() view over a plain dict, enough to
    exercise the pure ``_collect_stock_pairs`` helper without Frappe."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            return None


class TestCollectStockPairsPureHelper(unittest.TestCase):
    """Frappe-independent evidence that Sales/Purchase Invoice rows are
    only queued for a Bin check when ``update_stock`` is enabled, and that
    every other hooked doctype's rows are always collected."""

    def setUp(self):
        from synthetic_build_target_app.low_stock_alert_automation import (
            _collect_stock_pairs,
        )

        self.collect = _collect_stock_pairs

    def test_sales_invoice_without_update_stock_queues_nothing(self):
        doc = _DotDict(
            doctype="Sales Invoice",
            update_stock=0,
            items=[_DotDict(item_code="ITEM-A", warehouse="WH-1")],
        )
        self.assertEqual(self.collect(doc), set())

    def test_sales_invoice_with_update_stock_queues_its_rows(self):
        doc = _DotDict(
            doctype="Sales Invoice",
            update_stock=1,
            items=[_DotDict(item_code="ITEM-A", warehouse="WH-1")],
        )
        self.assertEqual(self.collect(doc), {("ITEM-A", "WH-1")})

    def test_purchase_invoice_without_update_stock_queues_nothing(self):
        doc = _DotDict(
            doctype="Purchase Invoice",
            update_stock=0,
            items=[_DotDict(item_code="ITEM-A", warehouse="WH-1")],
        )
        self.assertEqual(self.collect(doc), set())

    def test_stock_entry_collects_both_source_and_target_warehouse(self):
        doc = _DotDict(
            doctype="Stock Entry",
            items=[
                _DotDict(item_code="ITEM-A", s_warehouse="WH-SRC", t_warehouse="WH-DST")
            ],
        )
        self.assertEqual(
            self.collect(doc), {("ITEM-A", "WH-SRC"), ("ITEM-A", "WH-DST")}
        )

    def test_delivery_note_and_purchase_receipt_always_collected(self):
        dn = _DotDict(
            doctype="Delivery Note",
            items=[_DotDict(item_code="ITEM-A", warehouse="WH-1")],
        )
        pr = _DotDict(
            doctype="Purchase Receipt",
            items=[_DotDict(item_code="ITEM-B", warehouse="WH-2")],
        )
        self.assertEqual(self.collect(dn), {("ITEM-A", "WH-1")})
        self.assertEqual(self.collect(pr), {("ITEM-B", "WH-2")})

    def test_stock_reconciliation_always_collected(self):
        doc = _DotDict(
            doctype="Stock Reconciliation",
            items=[_DotDict(item_code="ITEM-A", warehouse="WH-1")],
        )
        self.assertEqual(self.collect(doc), {("ITEM-A", "WH-1")})


def _ensure_frappe_context():
    """Reuse the active bench execute DB context, or connect to the site."""
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


def _ensure_leaf(doctype, name_field, parent_field):
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
    _ensure_warehouse_type_transit()

    name = f"{PREFIX} Company"
    if frappe.db.exists("Company", name):
        return name

    company = frappe.get_doc(
        {
            "doctype": "Company",
            "company_name": name,
            "abbr": "ELSA",
            "default_currency": "USD",
            "country": "United States",
            "domain": "Services",
            "chart_of_accounts": "Standard",
        }
    )
    company.insert(ignore_permissions=True)
    return company.name


def _get_company_accounts(company):
    fields = [
        "default_currency",
        "default_income_account",
        "default_expense_account",
        "default_payable_account",
        "default_receivable_account",
        "cost_center",
        "stock_received_but_not_billed",
    ]
    row = frappe.db.get_value("Company", company, fields, as_dict=True)
    return row


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


def _ensure_warehouse_leaf(company):
    leaf = frappe.db.get_value(
        "Warehouse", {"company": company, "is_group": 0}, "name"
    )
    if leaf:
        return leaf

    root = frappe.db.get_value(
        "Warehouse", {"company": company, "is_group": 1}, "name"
    )
    name = f"{PREFIX}-WAREHOUSE"
    if frappe.db.exists("Warehouse", name):
        return name
    doc = frappe.get_doc(
        {
            "doctype": "Warehouse",
            "warehouse_name": name,
            "company": company,
            "parent_warehouse": root or None,
            "is_group": 0,
        }
    )
    doc.insert(ignore_permissions=True)
    return doc.name


def _ensure_stock_entry_type():
    name = "Material Receipt"
    if frappe.db.exists("Stock Entry Type", name):
        return name
    frappe.get_doc(
        {"doctype": "Stock Entry Type", "name": name, "purpose": "Material Receipt"}
    ).insert(ignore_permissions=True)
    return name


def _ensure_buying_price_list(currency):
    """A Buying Price List scoped to ``currency`` so Purchase Receipt /
    Purchase Invoice item-pricing lookups never need a cross-currency
    Currency Exchange record."""
    name = f"{PREFIX}-BUYING-PRICE-LIST-{currency}"
    if frappe.db.exists("Price List", name):
        return name
    price_list = frappe.get_doc(
        {
            "doctype": "Price List",
            "price_list_name": name,
            "currency": currency,
            "selling": 0,
            "buying": 1,
            "enabled": 1,
        }
    )
    price_list.insert(ignore_permissions=True)
    return price_list.name


def _ensure_selling_price_list(currency):
    """A Selling Price List scoped to ``currency`` for the same reason,
    used by Delivery Note / Sales Invoice."""
    name = f"{PREFIX}-SELLING-PRICE-LIST-{currency}"
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


def _ensure_stock_item(item_code, item_group, uom, important):
    if frappe.db.exists("Item", item_code):
        frappe.db.set_value("Item", item_code, "important_item", 1 if important else 0)
        return item_code
    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_code,
            "item_group": item_group,
            "stock_uom": uom,
            "is_stock_item": 1,
            "important_item": 1 if important else 0,
        }
    )
    item.insert(ignore_permissions=True)
    return item.name


def _make_customer():
    name = f"{PREFIX}-CUSTOMER"
    if frappe.db.exists("Customer", name):
        return name
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


def _make_supplier():
    name = f"{PREFIX}-SUPPLIER"
    if frappe.db.exists("Supplier", name):
        return name
    supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
    if not supplier_group:
        supplier_group = frappe.get_doc(
            {"doctype": "Supplier Group", "supplier_group_name": f"{PREFIX}-SG"}
        ).insert(ignore_permissions=True).name
    supplier = frappe.get_doc(
        {
            "doctype": "Supplier",
            "supplier_name": name,
            "supplier_group": supplier_group,
            "supplier_type": "Company",
        }
    )
    supplier.insert(ignore_permissions=True)
    return supplier.name


def _ensure_recipient_user():
    """A distinct, enabled Purchase Manager user other than Administrator,
    so Notification Log self-notification suppression cannot hide a
    missing alert."""
    email = f"{PREFIX.lower()}-purchase-manager@example.test"
    if not frappe.db.exists("User", email):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "EasytouchLSA",
                "last_name": "PurchaseManager",
                "send_welcome_email": 0,
                "enabled": 1,
                "roles": [{"role": "Purchase Manager"}],
            }
        )
        user.insert(ignore_permissions=True)
    else:
        user = frappe.get_doc("User", email)
        if not any(r.role == "Purchase Manager" for r in user.roles):
            user.append("roles", {"role": "Purchase Manager"})
            user.save(ignore_permissions=True)
        if not user.enabled:
            frappe.db.set_value("User", email, "enabled", 1)
    return email


def _bin_qty(item_code, warehouse):
    return (
        frappe.db.get_value(
            "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
        )
        or 0
    )


def _notification_count(item_code, recipient):
    return frappe.db.count(
        "Notification Log",
        {"document_type": "Item", "document_name": item_code, "for_user": recipient},
    )


def _submit_in_sync_notification_mode(doc):
    """Submit ``doc`` and commit while Frappe's own synchronous test path
    (``frappe.in_test``) is active, so the after-commit notification
    callback this automation registers runs synchronously instead of
    being handed to a background queue worker that the disposable
    bench-execute validation lanes do not run. The prior flag value is
    restored only after ``frappe.db.commit()`` completes, because
    after-commit callbacks run during that commit call."""
    previous = getattr(frappe, "in_test", False)
    frappe.in_test = True
    try:
        doc.submit()
        frappe.db.commit()
    finally:
        frappe.in_test = previous


def _cancel_in_sync_notification_mode(doc):
    """Same synchronous-test-path guarantee as
    ``_submit_in_sync_notification_mode``, for cancellation."""
    previous = getattr(frappe, "in_test", False)
    frappe.in_test = True
    try:
        doc.cancel()
        frappe.db.commit()
    finally:
        frappe.in_test = previous


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is unavailable in this local sandbox")
class TestLowStockAlertErpBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_frappe_context()
        from frappe.utils import nowdate

        cls.posting_date = nowdate()
        cls.company = _get_or_create_company()
        acc = _get_company_accounts(cls.company)
        cls.currency = acc.default_currency
        cls.income_account = acc.default_income_account
        cls.expense_account = acc.default_expense_account
        cls.payable_account = acc.default_payable_account
        cls.receivable_account = acc.default_receivable_account
        cls.cost_center = acc.cost_center
        _ensure_fiscal_year(cls.company, cls.posting_date)
        cls.uom = _ensure_uom()
        cls.item_group = _ensure_item_group_leaf()
        cls.warehouse = _ensure_warehouse_leaf(cls.company)
        cls.stock_entry_type = _ensure_stock_entry_type()
        cls.buying_price_list = _ensure_buying_price_list(cls.currency)
        cls.selling_price_list = _ensure_selling_price_list(cls.currency)
        cls.important_item = _ensure_stock_item(
            f"{PREFIX}-IMPORTANT-ITEM", cls.item_group, cls.uom, important=True
        )
        cls.normal_item = _ensure_stock_item(
            f"{PREFIX}-NORMAL-ITEM", cls.item_group, cls.uom, important=False
        )
        cls.customer = _make_customer()
        cls.supplier = _make_supplier()
        cls.recipient = _ensure_recipient_user()
        frappe.db.commit()

        cls.created_docs = []  # (doctype, name) in creation order

    @classmethod
    def tearDownClass(cls):
        for doctype, name in reversed(cls.created_docs):
            fresh = frappe.get_doc(doctype, name)
            if fresh.docstatus == 1:
                fresh.cancel()
            frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)

        for item_code in (cls.important_item, cls.normal_item):
            for log_name in frappe.get_all(
                "Notification Log",
                filters={
                    "document_type": "Item",
                    "document_name": item_code,
                    "for_user": cls.recipient,
                },
                pluck="name",
            ):
                frappe.delete_doc(
                    "Notification Log", log_name, force=1, ignore_permissions=True
                )

        if frappe.db.exists("User", cls.recipient):
            frappe.delete_doc("User", cls.recipient, force=1, ignore_permissions=True)
        if frappe.db.exists("Customer", cls.customer):
            frappe.delete_doc(
                "Customer", cls.customer, force=1, ignore_permissions=True
            )
        if frappe.db.exists("Supplier", cls.supplier):
            frappe.delete_doc(
                "Supplier", cls.supplier, force=1, ignore_permissions=True
            )
        for price_list in (cls.buying_price_list, cls.selling_price_list):
            if frappe.db.exists("Price List", price_list):
                frappe.delete_doc(
                    "Price List", price_list, force=1, ignore_permissions=True
                )

        frappe.db.commit()

    def _track(self, doc):
        self.created_docs.append((doc.doctype, doc.name))
        return doc

    def test_low_stock_alert_lifecycle_across_all_stock_sources(self):
        important = self.important_item
        normal = self.normal_item
        wh = self.warehouse

        baseline_important = _notification_count(important, self.recipient)
        baseline_normal = _notification_count(normal, self.recipient)
        expected_important_alerts = baseline_important

        # --- 1. Stock Entry (Material Receipt): seed 20 units of each item.
        # Above threshold -> no alert yet, for either item.
        se = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": self.stock_entry_type,
                "purpose": "Material Receipt",
                "company": self.company,
                "posting_date": self.posting_date,
                "set_posting_time": 1,
                "items": [
                    {
                        "item_code": important,
                        "qty": 20,
                        "t_warehouse": wh,
                        "basic_rate": 10,
                    },
                    {
                        "item_code": normal,
                        "qty": 20,
                        "t_warehouse": wh,
                        "basic_rate": 10,
                    },
                ],
            }
        )
        se.insert(ignore_permissions=True)
        self._track(se)
        _submit_in_sync_notification_mode(se)

        self.assertEqual(_bin_qty(important, wh), 20)
        self.assertEqual(_bin_qty(normal, wh), 20)
        self.assertEqual(
            _notification_count(important, self.recipient), expected_important_alerts
        )
        self.assertEqual(
            _notification_count(normal, self.recipient), baseline_normal
        )

        # --- 2. Purchase Receipt: receive 5 more of each -> still above
        # threshold; exercises the Purchase Receipt hook without alerting.
        # Currency/price-list fields are pinned explicitly so item pricing
        # lookup never adopts a foreign-currency default Price List.
        pr = frappe.get_doc(
            {
                "doctype": "Purchase Receipt",
                "supplier": self.supplier,
                "company": self.company,
                "currency": self.currency,
                "conversion_rate": 1,
                "buying_price_list": self.buying_price_list,
                "price_list_currency": self.currency,
                "plc_conversion_rate": 1,
                "posting_date": self.posting_date,
                "set_posting_time": 1,
                "items": [
                    {
                        "item_code": important,
                        "qty": 5,
                        "rate": 10,
                        "warehouse": wh,
                        "cost_center": self.cost_center,
                        "expense_account": self.expense_account,
                    },
                    {
                        "item_code": normal,
                        "qty": 5,
                        "rate": 10,
                        "warehouse": wh,
                        "cost_center": self.cost_center,
                        "expense_account": self.expense_account,
                    },
                ],
            }
        )
        pr.insert(ignore_permissions=True)
        self._track(pr)
        _submit_in_sync_notification_mode(pr)

        self.assertEqual(_bin_qty(important, wh), 25)
        self.assertEqual(_bin_qty(normal, wh), 25)
        self.assertEqual(
            _notification_count(important, self.recipient), expected_important_alerts
        )
        self.assertEqual(
            _notification_count(normal, self.recipient), baseline_normal
        )

        # --- 3. Delivery Note: deliver 18 of each -> both drop to 7, below
        # threshold. The marked item must alert; the unmarked item must not.
        dn = frappe.get_doc(
            {
                "doctype": "Delivery Note",
                "customer": self.customer,
                "company": self.company,
                "currency": self.currency,
                "conversion_rate": 1,
                "selling_price_list": self.selling_price_list,
                "price_list_currency": self.currency,
                "plc_conversion_rate": 1,
                "posting_date": self.posting_date,
                "set_posting_time": 1,
                "items": [
                    {
                        "item_code": important,
                        "qty": 18,
                        "rate": 15,
                        "warehouse": wh,
                        "cost_center": self.cost_center,
                        "expense_account": self.expense_account,
                        "income_account": self.income_account,
                    },
                    {
                        "item_code": normal,
                        "qty": 18,
                        "rate": 15,
                        "warehouse": wh,
                        "cost_center": self.cost_center,
                        "expense_account": self.expense_account,
                        "income_account": self.income_account,
                    },
                ],
            }
        )
        dn.insert(ignore_permissions=True)
        self._track(dn)
        _submit_in_sync_notification_mode(dn)

        self.assertEqual(_bin_qty(important, wh), 7)
        self.assertEqual(_bin_qty(normal, wh), 7)
        expected_important_alerts += 1
        self.assertEqual(
            _notification_count(important, self.recipient), expected_important_alerts
        )
        self.assertEqual(
            _notification_count(normal, self.recipient), baseline_normal
        )

        # --- 4. Purchase Invoice with update_stock=1: receive 20 more of
        # each -> rises back to 27, above threshold. Exercises the
        # Purchase Invoice (update_stock) hook; no new alert since the
        # crossing is upward.
        pi = frappe.get_doc(
            {
                "doctype": "Purchase Invoice",
                "supplier": self.supplier,
                "company": self.company,
                "currency": self.currency,
                "conversion_rate": 1,
                "buying_price_list": self.buying_price_list,
                "price_list_currency": self.currency,
                "plc_conversion_rate": 1,
                "update_stock": 1,
                "posting_date": self.posting_date,
                "due_date": self.posting_date,
                "set_posting_time": 1,
                "credit_to": self.payable_account,
                "items": [
                    {
                        "item_code": important,
                        "qty": 20,
                        "rate": 10,
                        "warehouse": wh,
                        "cost_center": self.cost_center,
                        "expense_account": self.expense_account,
                    },
                    {
                        "item_code": normal,
                        "qty": 20,
                        "rate": 10,
                        "warehouse": wh,
                        "cost_center": self.cost_center,
                        "expense_account": self.expense_account,
                    },
                ],
            }
        )
        pi.insert(ignore_permissions=True)
        self._track(pi)
        _submit_in_sync_notification_mode(pi)

        self.assertEqual(_bin_qty(important, wh), 27)
        self.assertEqual(_bin_qty(normal, wh), 27)
        self.assertEqual(
            _notification_count(important, self.recipient), expected_important_alerts
        )
        self.assertEqual(
            _notification_count(normal, self.recipient), baseline_normal
        )

        # --- 5. Sales Invoice with update_stock=1: deliver 20 of each via
        # direct invoice stock update -> drops back to 7, below threshold
        # again. Exercises the Sales Invoice (update_stock) hook.
        si = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.customer,
                "company": self.company,
                "currency": self.currency,
                "conversion_rate": 1,
                "selling_price_list": self.selling_price_list,
                "price_list_currency": self.currency,
                "plc_conversion_rate": 1,
                "update_stock": 1,
                "posting_date": self.posting_date,
                "due_date": self.posting_date,
                "set_posting_time": 1,
                "debit_to": self.receivable_account,
                "items": [
                    {
                        "item_code": important,
                        "qty": 20,
                        "rate": 15,
                        "warehouse": wh,
                        "income_account": self.income_account,
                        "cost_center": self.cost_center,
                    },
                    {
                        "item_code": normal,
                        "qty": 20,
                        "rate": 15,
                        "warehouse": wh,
                        "income_account": self.income_account,
                        "cost_center": self.cost_center,
                    },
                ],
            }
        )
        si.insert(ignore_permissions=True)
        self._track(si)
        _submit_in_sync_notification_mode(si)

        self.assertEqual(_bin_qty(important, wh), 7)
        self.assertEqual(_bin_qty(normal, wh), 7)
        expected_important_alerts += 1
        self.assertEqual(
            _notification_count(important, self.recipient), expected_important_alerts
        )
        self.assertEqual(
            _notification_count(normal, self.recipient), baseline_normal
        )

        # --- 6. Sales Invoice WITHOUT update_stock: must never queue a
        # Bin check, so the Bin and alert counts stay exactly unchanged
        # even though the invoiced quantity (100) would otherwise easily
        # cross the threshold if stock were (incorrectly) updated.
        si_no_stock = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.customer,
                "company": self.company,
                "currency": self.currency,
                "conversion_rate": 1,
                "selling_price_list": self.selling_price_list,
                "price_list_currency": self.currency,
                "plc_conversion_rate": 1,
                "update_stock": 0,
                "posting_date": self.posting_date,
                "due_date": self.posting_date,
                "set_posting_time": 1,
                "debit_to": self.receivable_account,
                "items": [
                    {
                        "item_code": important,
                        "qty": 100,
                        "rate": 15,
                        "income_account": self.income_account,
                        "cost_center": self.cost_center,
                    }
                ],
            }
        )
        si_no_stock.insert(ignore_permissions=True)
        self._track(si_no_stock)
        _submit_in_sync_notification_mode(si_no_stock)

        self.assertEqual(_bin_qty(important, wh), 7)
        self.assertEqual(
            _notification_count(important, self.recipient), expected_important_alerts
        )

        # --- 7. Stock Reconciliation: set both items' qty to 3 directly ->
        # below threshold. Exercises the Stock Reconciliation hook.
        sr = frappe.get_doc(
            {
                "doctype": "Stock Reconciliation",
                "purpose": "Stock Reconciliation",
                "company": self.company,
                "posting_date": self.posting_date,
                "set_posting_time": 1,
                "items": [
                    {
                        "item_code": important,
                        "warehouse": wh,
                        "qty": 3,
                        "valuation_rate": 10,
                    },
                    {
                        "item_code": normal,
                        "warehouse": wh,
                        "qty": 3,
                        "valuation_rate": 10,
                    },
                ],
            }
        )
        sr.insert(ignore_permissions=True)
        self._track(sr)
        _submit_in_sync_notification_mode(sr)

        self.assertEqual(_bin_qty(important, wh), 3)
        self.assertEqual(_bin_qty(normal, wh), 3)
        expected_important_alerts += 1
        self.assertEqual(
            _notification_count(important, self.recipient), expected_important_alerts
        )
        self.assertEqual(
            _notification_count(normal, self.recipient), baseline_normal
        )

        # --- 8. Cancel the Stock Reconciliation (the most recent stock
        # mutation): the reversed quantity must be recalculated back to the
        # pre-reconciliation Bin value (7), and the on_cancel hook must be
        # observed firing against that recalculated, still-below-threshold
        # quantity.
        _cancel_in_sync_notification_mode(sr)

        self.assertEqual(_bin_qty(important, wh), 7)
        self.assertEqual(_bin_qty(normal, wh), 7)
        expected_important_alerts += 1
        self.assertEqual(
            _notification_count(important, self.recipient), expected_important_alerts
        )
        self.assertEqual(
            _notification_count(normal, self.recipient), baseline_normal
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
