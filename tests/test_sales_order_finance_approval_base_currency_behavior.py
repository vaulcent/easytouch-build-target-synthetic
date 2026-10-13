"""Authoritative ERPNext v16 behavior evidence that the "Sales Order
Finance Approval" Workflow's $5,000 threshold is evaluated in the
Company's base currency (``base_grand_total``), never the transaction
currency's raw ``grand_total`` (see fixtures/workflow.json).

Seeds a real foreign-currency (EUR) Sales Order against a USD-base
Company with a non-unit, non-hardcoded exchange rate backed by a real
Currency Exchange record, chosen so the order's raw EUR grand_total and
USD base_grand_total land on OPPOSITE sides of the $5,000 threshold:

    rate = 4,000 EUR, qty = 1 -> grand_total = 4,000 EUR (<= 5000)
    conversion_rate = 1.4     -> base_grand_total = 5,600 USD (> 5000)

A same-currency fixture (grand_total == base_grand_total) cannot expose
a currency-handling error; this one proves the workflow actually reads
the base amount: the Sales User must NOT be able to self-submit this
order (base_grand_total > 5000 even though raw grand_total <= 5000), it
must instead route to "Pending Finance Approval", and only the "Finance
Approval" role can then approve it.

This is a compact, dedicated module for this one base-currency
correctness requirement, layered on top of the existing "Sales Order
Finance Approval" Workflow fixture exercised more broadly by
tests/test_sales_order_finance_approval_workflow_behavior.py. It does
not duplicate that module's same-currency state/transition coverage.

Loaded by ``bench execute`` with an active Frappe database context:
reuses ``frappe.local.db`` when already present, and only initializes
from ``frappe.local.site`` when needed. Skips only when Frappe itself is
unavailable in this local coding sandbox.
"""

from __future__ import annotations

import importlib.util
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("workflow",)

FRAPPE_AVAILABLE = importlib.util.find_spec("frappe") is not None


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; this authoritative "
    "case must run inside a real disposable ERPNext v16 site via "
    "bench execute.",
)
class TestSalesOrderFinanceApprovalBaseCurrencyBehavior(unittest.TestCase):
    CUSTOMER_NAME = "Easytouch Finance Approval Currency Test Customer"
    ITEM_CODE = "EASYTOUCH-FINANCE-APPROVAL-CURRENCY-TEST-SERVICE"
    SALESPERSON_EMAIL = "easytouch-finance-approval-currency-salesperson@example.test"
    FINANCE_APPROVER_EMAIL = "easytouch-finance-approval-currency-approver@example.test"

    FOREIGN_CURRENCY = "EUR"
    EXCHANGE_RATE = 1.4  # 1 EUR = 1.4 USD (non-unit, real Currency Exchange record)
    FOREIGN_RATE = 4000  # raw grand_total (EUR) <= 5000 threshold
    # base_grand_total = 4000 * 1.4 = 5600 USD -> > 5000 threshold

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
        assert cls.company_currency == "USD", (
            "This scenario requires a USD-base Company so the EUR "
            "foreign-currency order exercises a real cross-currency "
            "conversion."
        )
        cls._ensure_currency_exchange(
            cls.FOREIGN_CURRENCY, cls.company_currency, cls.EXCHANGE_RATE
        )
        cls._ensure_fiscal_year(cls.company)
        cls.customer_group = cls._ensure_leaf_customer_group()
        cls.territory = cls._ensure_leaf_territory()
        cls.customer = cls._ensure_customer()
        cls.item_code = cls._ensure_service_item()

        assert frappe.db.exists("Role", "Finance Approval"), (
            "The 'Finance Approval' Role fixture must be imported before "
            "the 'Sales Order Finance Approval' Workflow fixture."
        )

        cls.salesperson_user = cls._ensure_user(cls.SALESPERSON_EMAIL, "Sales User")
        cls.finance_approver_user = cls._ensure_user(
            cls.FINANCE_APPROVER_EMAIL, "Finance Approval"
        )

        for user, role in (
            (cls.salesperson_user, "Sales User"),
            (cls.finance_approver_user, "Finance Approval"),
        ):
            cls._ensure_actor_can_read_dependencies(user, role)

    @classmethod
    def tearDownClass(cls):
        cls.frappe.set_user("Administrator")

    # -- master-data setup ---------------------------------------------------

    @classmethod
    def _ensure_company(cls):
        frappe = cls.frappe
        name = "Easytouch Finance Approval Currency Test Co"
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
        company = frappe.get_doc(
            {
                "doctype": "Company",
                "company_name": name,
                "abbr": "EFCT",
                "default_currency": "USD",
                "country": "United States",
            }
        )
        company.insert(ignore_permissions=True)
        frappe.db.commit()
        return company.name

    @classmethod
    def _ensure_currency_exchange(cls, from_currency, to_currency, rate):
        frappe = cls.frappe
        if not frappe.db.exists("Currency", from_currency):
            frappe.get_doc(
                {"doctype": "Currency", "currency_name": from_currency}
            ).insert(ignore_permissions=True)
        if not frappe.db.get_value("Currency", from_currency, "enabled"):
            frappe.db.set_value("Currency", from_currency, "enabled", 1)

        today = frappe.utils.nowdate()
        existing = frappe.get_all(
            "Currency Exchange",
            filters={
                "from_currency": from_currency,
                "to_currency": to_currency,
                "date": today,
            },
            pluck="name",
            limit=1,
        )
        if existing:
            doc = frappe.get_doc("Currency Exchange", existing[0])
            if doc.exchange_rate != rate:
                doc.exchange_rate = rate
                doc.save(ignore_permissions=True)
            return doc.name
        doc = frappe.get_doc(
            {
                "doctype": "Currency Exchange",
                "date": today,
                "from_currency": from_currency,
                "to_currency": to_currency,
                "exchange_rate": rate,
            }
        )
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return doc.name

    @classmethod
    def _ensure_fiscal_year(cls, company):
        frappe = cls.frappe
        today = frappe.utils.nowdate()

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

        from datetime import timedelta

        from frappe.utils import add_years, get_first_day

        start = get_first_day(today).replace(month=1, day=1)
        end = add_years(start, 1) - timedelta(days=1)

        fy = frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": "Easytouch Finance Approval Currency Test FY %s" % today,
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
                "customer_group_name": "Easytouch Finance Approval Currency Test Group",
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
                "territory_name": "Easytouch Finance Approval Currency Test Territory",
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
                    "item_group_name": "Easytouch Finance Approval Currency Test Items",
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

    @classmethod
    def _ensure_user(cls, email, role):
        frappe = cls.frappe
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": email.split("@")[0],
                    "send_welcome_email": 0,
                    "user_type": "System User",
                }
            )
            user.insert(ignore_permissions=True)
        existing_roles = {row.role for row in user.get("roles") or []}
        if role not in existing_roles:
            user.append("roles", {"role": role})
            user.save(ignore_permissions=True)
        frappe.db.commit()
        return user.name

    @classmethod
    def _ensure_actor_can_read_dependencies(cls, user, workflow_role):
        frappe = cls.frappe
        for doctype in ("Customer", "Item", "Company"):
            meta = frappe.get_meta(doctype)
            readable_roles = {
                perm.role
                for perm in meta.permissions
                if (perm.permlevel or 0) == 0 and perm.read
            }
            if workflow_role in readable_roles:
                continue
            user_doc = frappe.get_doc("User", user)
            current_roles = {row.role for row in user_doc.get("roles") or []}
            if current_roles & readable_roles:
                continue
            baseline_candidates = sorted(readable_roles - {"All", "Guest"})
            if not baseline_candidates:
                continue
            baseline_role = baseline_candidates[0]
            user_doc.append("roles", {"role": baseline_role})
            user_doc.save(ignore_permissions=True)
            frappe.db.commit()

    # -- document construction -----------------------------------------------

    def _make_foreign_currency_order(self):
        frappe = self.frappe
        frappe.set_user(self.salesperson_user)

        self.assertTrue(
            frappe.has_permission(doctype="Customer", doc=self.customer, ptype="read"),
        )
        self.assertTrue(
            frappe.has_permission(doctype="Item", doc=self.item_code, ptype="read"),
        )

        today = frappe.utils.nowdate()
        order = frappe.get_doc(
            {
                "doctype": "Sales Order",
                "customer": self.customer,
                "company": self.company,
                "currency": self.FOREIGN_CURRENCY,
                "conversion_rate": self.EXCHANGE_RATE,
                "order_type": "Sales",
                "transaction_date": today,
                "delivery_date": today,
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 1,
                        "rate": self.FOREIGN_RATE,
                        "delivery_date": today,
                    }
                ],
            }
        )
        order.insert()
        frappe.db.commit()
        return order.name

    # -- behavior test ---------------------------------------------------------

    def test_threshold_is_evaluated_in_base_currency_not_transaction_currency(self):
        frappe = self.frappe
        from frappe.model.workflow import apply_workflow, get_transitions

        try:
            order_name = self._make_foreign_currency_order()
            order = frappe.get_doc("Sales Order", order_name)
            self.assertEqual(order.workflow_state, "Draft")

            # The scenario: raw EUR grand_total <= 5000 but USD
            # base_grand_total > 5000 -- opposite sides of the threshold.
            self.assertLessEqual(order.grand_total, 5000)
            self.assertGreater(order.base_grand_total, 5000)

            frappe.set_user(self.salesperson_user)
            self.assertEqual(frappe.session.user, self.salesperson_user)
            self.assertIn("Sales User", frappe.get_roles(self.salesperson_user))

            # The "Submit" (self-approve) transition's real condition
            # must be evaluated against base_grand_total, so it must be
            # excluded even though the raw/transaction-currency
            # grand_total is <= 5000.
            visible_actions = {row.action for row in get_transitions(order)}
            self.assertNotIn(
                "Submit",
                visible_actions,
                "The self-submit 'Submit' transition must be excluded "
                "when base_grand_total exceeds the $5,000 threshold, "
                "even though the raw transaction-currency grand_total "
                "does not.",
            )
            self.assertIn("Send for Finance Approval", visible_actions)

            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Order",
                    doc=order,
                    ptype="write",
                    user=self.salesperson_user,
                ),
            )
            apply_workflow(order, "Send for Finance Approval")
            frappe.db.commit()
        finally:
            frappe.set_user("Administrator")

        routed = frappe.get_doc("Sales Order", order_name)
        self.assertEqual(routed.workflow_state, "Pending Finance Approval")
        self.assertEqual(routed.docstatus, 0)

        try:
            frappe.set_user(self.finance_approver_user)
            self.assertEqual(frappe.session.user, self.finance_approver_user)
            self.assertIn(
                "Finance Approval", frappe.get_roles(self.finance_approver_user)
            )
            pending = frappe.get_doc("Sales Order", order_name)
            self.assertIn(
                "Approve", {row.action for row in get_transitions(pending)}
            )
            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Order",
                    doc=pending,
                    ptype="submit",
                    user=self.finance_approver_user,
                ),
            )
            apply_workflow(pending, "Approve")
            frappe.db.commit()
        finally:
            frappe.set_user("Administrator")

        approved = frappe.get_doc("Sales Order", order_name)
        self.assertEqual(approved.workflow_state, "Approved")
        self.assertEqual(approved.docstatus, 1)
