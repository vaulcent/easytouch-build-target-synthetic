"""Authoritative ERPNext v16 behavior evidence for the repaired Important
Item Low Stock Alert.

Proves, against a real disposable ERPNext v16 site with no outgoing Email
Account configured, that submitting a real stock movement (a Stock Entry)
on an important item that drops its warehouse Bin's ``actual_qty`` below
10 creates a real Notification Log for a Purchase Manager recipient via
the Notification's "System Notification" channel -- never via Email, and
never via a mocked Frappe/database stand-in.

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
        cls.warehouse = cls._ensure_warehouse(cls.company)
        cls.item_code = cls._ensure_important_item()
        cls._ensure_fiscal_year(cls.company)
        cls.recipient = cls._ensure_purchase_manager_recipient()
        cls.receipt_type = cls._ensure_stock_entry_type("Material Receipt")
        cls.issue_type = cls._ensure_stock_entry_type("Material Issue")

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
    def _ensure_important_item(cls):
        frappe = cls.frappe
        code = cls.ITEM_CODE
        if frappe.db.exists("Item", code):
            item = frappe.get_doc("Item", code)
            if not item.is_important_item:
                item.is_important_item = 1
                item.save(ignore_permissions=True)
            return item.name
        item_group = cls._ensure_item_group()
        uom = cls._ensure_uom()
        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": code,
                "item_name": code,
                "item_group": item_group,
                "stock_uom": uom,
                "is_stock_item": 1,
                "is_important_item": 1,
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

    # -- behavior test ------------------------------------------------------

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

        before_count = frappe.db.count(
            "Notification Log",
            {"for_user": self.recipient, "document_type": "Bin"},
        )

        assert frappe.db.count("Email Account", {"enable_outgoing": 1}) == 0

        # Real synchronous after-commit notification path: set
        # frappe.in_test around the real triggering transaction and its
        # commit, restoring it only after that commit.
        previous_in_test = frappe.in_test
        frappe.in_test = True
        try:
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
            issue.submit()
            frappe.db.commit()
        finally:
            frappe.in_test = previous_in_test

        actual_qty = frappe.db.get_value(
            "Bin",
            {"item_code": self.item_code, "warehouse": self.warehouse},
            "actual_qty",
        )
        self.assertLess(actual_qty, 10)

        after_count = frappe.db.count(
            "Notification Log",
            {"for_user": self.recipient, "document_type": "Bin"},
        )
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


if __name__ == "__main__":
    unittest.main()
