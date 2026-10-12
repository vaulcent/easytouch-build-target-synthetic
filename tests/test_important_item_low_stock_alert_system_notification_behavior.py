"""Authoritative ERPNext v16 behavior evidence for the repaired Important
Item Low Stock Alert.

Proves, against a real disposable ERPNext v16 site with no outgoing Email
Account configured, that submitting (or cancelling) a real stock
movement on an important item that drops its warehouse Bin's
``actual_qty`` below 10 creates a real Notification Log for a Purchase
Manager recipient via the Notification's "System Notification" channel --
never via Email, and never via a mocked Frappe/database stand-in. Real
stock-changing source transactions are exercised: Stock Entry, Purchase
Receipt, and Delivery Note. An unmarked item is proved to never alert,
and cancelling a stock-reducing transaction is proved to recalculate the
reversed quantity back above the threshold.

Every buying/selling transaction created here explicitly sets its own
``currency`` to the test Company's own default currency and
``conversion_rate`` to 1, and explicitly sets its own Price List fields
(``buying_price_list``/``selling_price_list``, ``price_list_currency``,
``plc_conversion_rate``) to Price List masters this module itself
ensures exist (creating them if absent) rather than assuming a pristine
ERPNext v16 site ships "Standard Buying"/"Standard Selling" masters by
that name. A minimal fresh site may have neither record at all, which
previously raised ``LinkValidationError: Could not find Price List:
Standard Buying`` when a document referenced that name without first
confirming (or creating) it. Ensuring the Price List exists -- in the
test Company's own currency, so no Currency Exchange master is ever
needed -- avoids both that missing-link failure and any "Exchange Rate
is mandatory" failure from a currency mismatch.

Loaded by ``bench execute`` with an active Frappe database context: reuses
``frappe.local.db`` when already present, and only initializes from
``frappe.local.site`` when needed. Skips only when Frappe itself is
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
class TestImportantItemLowStockAlertSystemNotificationBehavior(unittest.TestCase):
    RECIPIENT_EMAIL = "easytouch.purchase.manager.lowstock.test@example.com"
    ITEM_CODE = "EASYTOUCH-LOW-STOCK-IMPORTANT-ITEM"

    @classmethod
    def setUpClass(cls):
        import frappe

        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        cls.frappe = frappe
        frappe.set_user("Administrator")

        cls._ensure_no_outgoing_email_account()
        cls.company = cls._ensure_company()
        cls.currency = frappe.get_cached_value(
            "Company", cls.company, "default_currency"
        )
        cls.warehouse = cls._ensure_warehouse(cls.company)
        cls.item_group = cls._ensure_item_group()
        cls.uom = cls._ensure_uom()
        cls.item_code = cls._ensure_important_item(cls.ITEM_CODE)
        cls._ensure_fiscal_year(cls.company)
        cls.recipient = cls._ensure_purchase_manager_recipient()
        cls.receipt_type = cls._ensure_stock_entry_type("Material Receipt")
        cls.issue_type = cls._ensure_stock_entry_type("Material Issue")
        cls.customer = cls._ensure_customer()
        cls.supplier = cls._ensure_supplier()
        cls.buying_price_list = cls._ensure_price_list(
            "Standard Buying", cls.currency, buying=1
        )
        cls.selling_price_list = cls._ensure_price_list(
            "Standard Selling", cls.currency, selling=1
        )

    # -- master-data setup -------------------------------------------------

    @classmethod
    def _ensure_no_outgoing_email_account(cls):
        frappe = cls.frappe
        for name in frappe.get_all(
            "Email Account", filters={"enable_outgoing": 1}, pluck="name"
        ):
            frappe.db.set_value("Email Account", name, "enable_outgoing", 0)
        frappe.db.commit()
        assert frappe.db.count("Email Account", {"enable_outgoing": 1}) == 0

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
                "company_name": "Easytouch Low Stock Behavior Test Co",
                "abbr": "ELSBT",
                "default_currency": "USD",
                "country": "United States",
            }
        )
        company.insert(ignore_permissions=True)
        frappe.db.commit()
        return company.name

    @classmethod
    def _ensure_warehouse(cls, company):
        frappe = cls.frappe
        existing = frappe.get_all(
            "Warehouse",
            filters={"company": company, "is_group": 0},
            pluck="name",
            limit=1,
        )
        if existing:
            return existing[0]
        warehouse = frappe.get_doc(
            {
                "doctype": "Warehouse",
                "warehouse_name": "Easytouch Low Stock Behavior Test Store",
                "company": company,
            }
        )
        warehouse.insert(ignore_permissions=True)
        frappe.db.commit()
        return warehouse.name

    @classmethod
    def _ensure_item_group(cls):
        frappe = cls.frappe
        leaf = frappe.get_all(
            "Item Group", filters={"is_group": 0}, pluck="name", limit=1
        )
        if leaf:
            return leaf[0]
        root = frappe.get_all(
            "Item Group", filters={"is_group": 1}, pluck="name", limit=1
        )
        if root:
            root_name = root[0]
        else:
            root_doc = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "All Item Groups",
                    "is_group": 1,
                }
            )
            root_doc.insert(ignore_permissions=True)
            root_name = root_doc.name
        leaf_doc = frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": "Easytouch Low Stock Behavior Test Items",
                "is_group": 0,
                "parent_item_group": root_name,
            }
        )
        leaf_doc.insert(ignore_permissions=True)
        return leaf_doc.name

    @classmethod
    def _ensure_uom(cls):
        frappe = cls.frappe
        if frappe.db.exists("UOM", "Nos"):
            return "Nos"
        frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(
            ignore_permissions=True
        )
        return "Nos"

    @classmethod
    def _ensure_important_item(cls, code, important=True):
        frappe = cls.frappe
        if frappe.db.exists("Item", code):
            item = frappe.get_doc("Item", code)
            if bool(item.is_important_item) != bool(important):
                item.is_important_item = 1 if important else 0
                item.save(ignore_permissions=True)
            return item.name
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": code,
                "item_name": code,
                "item_group": cls.item_group,
                "stock_uom": cls.uom,
                "is_stock_item": 1,
                "is_important_item": 1 if important else 0,
            }
        )
        item.insert(ignore_permissions=True)
        return item.name

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
                "year": "Easytouch Low Stock Test FY %d" % year,
                "year_start_date": start,
                "year_end_date": end,
            }
        )
        fy.append("companies", {"company": company})
        fy.insert(ignore_permissions=True)
        return fy.name

    @classmethod
    def _ensure_stock_entry_type(cls, purpose):
        frappe = cls.frappe
        existing = frappe.get_all(
            "Stock Entry Type", filters={"purpose": purpose}, pluck="name", limit=1
        )
        if existing:
            return existing[0]
        doc = frappe.get_doc(
            {"doctype": "Stock Entry Type", "name": purpose, "purpose": purpose}
        )
        doc.insert(ignore_permissions=True)
        return doc.name

    @classmethod
    def _ensure_purchase_manager_recipient(cls):
        frappe = cls.frappe
        email = cls.RECIPIENT_EMAIL
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Easytouch Purchase Manager Test",
                    "send_welcome_email": 0,
                    "enabled": 1,
                    "user_type": "System User",
                }
            )
            user.insert(ignore_permissions=True)
        if not user.enabled:
            user.enabled = 1
            user.save(ignore_permissions=True)
        if not any(row.role == "Purchase Manager" for row in user.roles):
            user.append("roles", {"role": "Purchase Manager"})
            user.save(ignore_permissions=True)
        frappe.db.commit()
        return user.name

    @classmethod
    def _ensure_leaf_group(cls, doctype, root_field, root_name_value, leaf_name_value):
        frappe = cls.frappe
        leaf = frappe.get_all(
            doctype, filters={"is_group": 0}, pluck="name", limit=1
        )
        if leaf:
            return leaf[0]
        root = frappe.get_all(doctype, filters={"is_group": 1}, pluck="name", limit=1)
        if root:
            root_name = root[0]
        else:
            root_doc = frappe.get_doc(
                {"doctype": doctype, root_field: root_name_value, "is_group": 1}
            )
            root_doc.insert(ignore_permissions=True)
            root_name = root_doc.name
        parent_field = {
            "Customer Group": "parent_customer_group",
            "Territory": "parent_territory",
            "Supplier Group": "parent_supplier_group",
        }[doctype]
        leaf_doc = frappe.get_doc(
            {
                "doctype": doctype,
                root_field: leaf_name_value,
                "is_group": 0,
                parent_field: root_name,
            }
        )
        leaf_doc.insert(ignore_permissions=True)
        return leaf_doc.name

    @classmethod
    def _ensure_customer(cls):
        frappe = cls.frappe
        name = "Easytouch Low Stock Behavior Test Customer"
        if frappe.db.exists("Customer", name):
            return name
        customer_group = cls._ensure_leaf_group(
            "Customer Group",
            "customer_group_name",
            "All Customer Groups",
            "Easytouch Low Stock Behavior Test Customer Group",
        )
        territory = cls._ensure_leaf_group(
            "Territory",
            "territory_name",
            "All Territories",
            "Easytouch Low Stock Behavior Test Territory",
        )
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": name,
                "customer_group": customer_group,
                "territory": territory,
                "customer_type": "Company",
            }
        )
        customer.insert(ignore_permissions=True)
        return customer.name

    @classmethod
    def _ensure_supplier(cls):
        frappe = cls.frappe
        name = "Easytouch Low Stock Behavior Test Supplier"
        if frappe.db.exists("Supplier", name):
            return name
        supplier_group = cls._ensure_leaf_group(
            "Supplier Group",
            "supplier_group_name",
            "All Supplier Groups",
            "Easytouch Low Stock Behavior Test Supplier Group",
        )
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

    @classmethod
    def _ensure_price_list(cls, name, currency, buying=0, selling=0):
        """Ensure a Price List named ``name`` exists in ``currency``.

        A pristine/minimal ERPNext v16 site is not guaranteed to ship
        "Standard Buying"/"Standard Selling" Price List masters by that
        name at all; referencing either name on a Purchase Receipt or
        Delivery Note without first confirming (or creating) it raises
        ``frappe.exceptions.LinkValidationError: Could not find Price
        List: <name>``. This creates the master, scoped to the test
        Company's own ``currency`` (never a different currency), only
        when it is missing -- idempotent and safe to call repeatedly.
        """
        frappe = cls.frappe
        if frappe.db.exists("Price List", name):
            if frappe.db.get_value("Price List", name, "currency") != currency:
                frappe.db.set_value("Price List", name, "currency", currency)
            if buying and not frappe.db.get_value("Price List", name, "buying"):
                frappe.db.set_value("Price List", name, "buying", 1)
            if selling and not frappe.db.get_value("Price List", name, "selling"):
                frappe.db.set_value("Price List", name, "selling", 1)
            frappe.db.commit()
            return name
        price_list = frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": name,
                "currency": currency,
                "buying": 1 if buying else 0,
                "selling": 1 if selling else 0,
                "enabled": 1,
            }
        )
        price_list.insert(ignore_permissions=True)
        frappe.db.commit()
        return price_list.name

    @classmethod
    def _notification_log_count(cls):
        return cls.frappe.db.count(
            "Notification Log",
            {"for_user": cls.recipient, "document_type": "Bin"},
        )

    @classmethod
    def _submit_in_test_mode(cls, doc):
        """Submit ``doc`` with frappe.in_test True around submit + commit.

        Frappe's real System Notification path normally enqueues
        Notification Log creation; setting frappe.in_test = True around
        the real triggering transaction and its commit uses Frappe's own
        synchronous test path so the Notification Log is created
        immediately, in-line with this commit, rather than asynchronously.
        """
        frappe = cls.frappe
        previous_in_test = frappe.in_test
        frappe.in_test = True
        try:
            doc.submit()
            frappe.db.commit()
        finally:
            frappe.in_test = previous_in_test

    @classmethod
    def _cancel_in_test_mode(cls, doc):
        frappe = cls.frappe
        previous_in_test = frappe.in_test
        frappe.in_test = True
        try:
            doc.reload()
            doc.cancel()
            frappe.db.commit()
        finally:
            frappe.in_test = previous_in_test

    @classmethod
    def _bin_qty(cls, item_code, warehouse):
        return cls.frappe.db.get_value(
            "Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"
        )

    # -- behavior tests ------------------------------------------------------

    def test_real_stock_movement_creates_notification_log_without_email_account(
        self,
    ):
        frappe = self.frappe

        # Bring the important item's Bin up to 15 (>= 10): must NOT alert.
        receipt = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": self.receipt_type,
                "purpose": "Material Receipt",
                "company": self.company,
                "posting_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 15,
                        "t_warehouse": self.warehouse,
                        "basic_rate": 10,
                    }
                ],
            }
        )
        receipt.insert(ignore_permissions=True)
        receipt.submit()
        frappe.db.commit()

        before_count = self._notification_log_count()

        assert frappe.db.count("Email Account", {"enable_outgoing": 1}) == 0

        issue = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": self.issue_type,
                "purpose": "Material Issue",
                "company": self.company,
                "posting_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 10,
                        "s_warehouse": self.warehouse,
                    }
                ],
            }
        )
        issue.insert(ignore_permissions=True)
        self._submit_in_test_mode(issue)

        actual_qty = self._bin_qty(self.item_code, self.warehouse)
        self.assertLess(actual_qty, 10)

        after_count = self._notification_log_count()
        self.assertEqual(
            after_count,
            before_count + 1,
            "exactly one new Notification Log must be created for the "
            "Purchase Manager recipient once the important item's Bin "
            "actual_qty drops below 10",
        )

        log_name = frappe.get_all(
            "Notification Log",
            filters={"for_user": self.recipient, "document_type": "Bin"},
            order_by="creation desc",
            limit=1,
            pluck="name",
        )[0]
        log = frappe.get_doc("Notification Log", log_name)
        self.assertEqual(log.for_user, self.recipient)
        self.assertIn(self.item_code, log.subject or "")

    def test_unmarked_item_below_threshold_does_not_alert(self):
        frappe = self.frappe
        unimportant_item = self._ensure_important_item(
            "EASYTOUCH-LOW-STOCK-UNIMPORTANT-ITEM", important=False
        )

        before_count = self._notification_log_count()

        receipt_type = self._ensure_stock_entry_type("Material Receipt")

        receipt = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": receipt_type,
                "purpose": "Material Receipt",
                "company": self.company,
                "posting_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": unimportant_item,
                        "qty": 5,
                        "t_warehouse": self.warehouse,
                        "basic_rate": 10,
                    }
                ],
            }
        )
        receipt.insert(ignore_permissions=True)
        self._submit_in_test_mode(receipt)

        actual_qty = self._bin_qty(unimportant_item, self.warehouse)
        self.assertLess(actual_qty, 10)

        after_count = self._notification_log_count()
        self.assertEqual(
            after_count,
            before_count,
            "an unmarked (not important) item dropping below the "
            "threshold must never create a Notification Log",
        )

    def test_cancellation_recalculates_reversed_quantity(self):
        frappe = self.frappe
        item_code = self._ensure_important_item(
            "EASYTOUCH-LOW-STOCK-CANCEL-ITEM", important=True
        )
        receipt_type = self._ensure_stock_entry_type("Material Receipt")
        issue_type = self._ensure_stock_entry_type("Material Issue")

        receipt = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": receipt_type,
                "purpose": "Material Receipt",
                "company": self.company,
                "posting_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": item_code,
                        "qty": 15,
                        "t_warehouse": self.warehouse,
                        "basic_rate": 10,
                    }
                ],
            }
        )
        receipt.insert(ignore_permissions=True)
        receipt.submit()
        frappe.db.commit()

        baseline_qty = self._bin_qty(item_code, self.warehouse)
        self.assertGreaterEqual(baseline_qty, 10)

        issue = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": issue_type,
                "purpose": "Material Issue",
                "company": self.company,
                "posting_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": item_code,
                        "qty": 10,
                        "s_warehouse": self.warehouse,
                    }
                ],
            }
        )
        issue.insert(ignore_permissions=True)
        self._submit_in_test_mode(issue)

        reduced_qty = self._bin_qty(item_code, self.warehouse)
        self.assertLess(
            reduced_qty,
            10,
            "submitting the Material Issue must drop the Bin below the "
            "low-stock threshold",
        )

        count_after_issue = self._notification_log_count()
        self.assertGreaterEqual(
            count_after_issue,
            1,
            "the Material Issue dropping an important item's Bin below "
            "the threshold must create a Notification Log",
        )

        # Cancelling the stock-reducing transaction must recalculate the
        # reversed quantity back above the threshold.
        self._cancel_in_test_mode(issue)

        reversed_qty = self._bin_qty(item_code, self.warehouse)
        self.assertGreaterEqual(
            reversed_qty,
            10,
            "cancelling the Material Issue must recalculate the "
            "reversed Bin quantity back above the low-stock threshold",
        )

    def test_purchase_receipt_and_delivery_note_also_trigger_alert(self):
        frappe = self.frappe
        item_code = self._ensure_important_item(
            "EASYTOUCH-LOW-STOCK-PR-DN-ITEM", important=True
        )

        # Purchase Receipt brings the Bin up to 15 (>= 10): must NOT alert.
        purchase_receipt = frappe.get_doc(
            {
                "doctype": "Purchase Receipt",
                "company": self.company,
                "supplier": self.supplier,
                "posting_date": frappe.utils.nowdate(),
                "currency": self.currency,
                "conversion_rate": 1,
                "buying_price_list": self.buying_price_list,
                "price_list_currency": self.currency,
                "plc_conversion_rate": 1,
                "items": [
                    {
                        "item_code": item_code,
                        "qty": 15,
                        "rate": 10,
                        "warehouse": self.warehouse,
                    }
                ],
            }
        )
        purchase_receipt.insert(ignore_permissions=True)
        purchase_receipt.submit()
        frappe.db.commit()

        baseline_qty = self._bin_qty(item_code, self.warehouse)
        self.assertGreaterEqual(baseline_qty, 10)

        before_count = self._notification_log_count()

        # Delivery Note reduces the Bin to 5 (< 10): must alert.
        delivery_note = frappe.get_doc(
            {
                "doctype": "Delivery Note",
                "company": self.company,
                "customer": self.customer,
                "posting_date": frappe.utils.nowdate(),
                "currency": self.currency,
                "conversion_rate": 1,
                "selling_price_list": self.selling_price_list,
                "price_list_currency": self.currency,
                "plc_conversion_rate": 1,
                "items": [
                    {
                        "item_code": item_code,
                        "qty": 10,
                        "rate": 20,
                        "warehouse": self.warehouse,
                    }
                ],
            }
        )
        delivery_note.insert(ignore_permissions=True)
        self._submit_in_test_mode(delivery_note)

        actual_qty = self._bin_qty(item_code, self.warehouse)
        self.assertLess(actual_qty, 10)

        after_count = self._notification_log_count()
        self.assertEqual(
            after_count,
            before_count + 1,
            "the Delivery Note dropping an important item's Bin below "
            "the threshold must create exactly one new Notification Log "
            "for the Purchase Manager recipient",
        )
