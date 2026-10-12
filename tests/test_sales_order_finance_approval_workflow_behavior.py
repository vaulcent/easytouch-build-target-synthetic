"""Authoritative ERPNext v16 behavior evidence for the "Sales Order
Finance Approval" Workflow requirement: a salesperson must not be able
to approve (submit) a Sales Order above $5,000 themselves; any order
above that grand_total threshold must be routed to a user holding the
"Finance Approval" role before it can reach "Approved".

State / transition / permission matrix this test exercises end-to-end
against a real disposable ERPNext v16 site (see fixtures/workflow.json,
fixtures/workflow_state.json, fixtures/workflow_action_master.json,
fixtures/role.json, and synthetic_build_target_app.synthetic_build_
target_app.install.ensure_sales_order_finance_approval_workflow_
permissions for the fixtures/installer this proves):

    state                       docstatus  allow_edit role
    Draft                       0          Sales User
    Pending Finance Approval    0          Finance Approval
    Approved                    1          Finance Approval

    transition                                             allowed role      condition             underlying live permission required
    Draft -> Approved          (action "Submit")            Sales User        grand_total <= 5000   SUBMIT on Sales Order (next docstatus=1)
    Draft -> Pending Fin.Appr. (action "Send for Finance Approval") Sales User grand_total > 5000   WRITE on Sales Order (next docstatus=0, ordinary save)
    Pending Fin.Appr -> Approved(action "Approve")          Finance Approval  grand_total > 5000    SUBMIT on Sales Order (next docstatus=1)

Both the allowed and the denied paths are exercised as real, distinct
Frappe users/sessions (the requirement's named actor,
owner@nasiib.example, acts as the Sales User who creates and attempts to
submit orders; a distinct Finance Approval-role user is required to
actually approve a routed order, since a workflow role never bypasses
ordinary DocType permissions and the self-approval guard rejects the
owner's own high-value submit), asserting ``frappe.session.user`` and
``frappe.get_roles()`` immediately before every ``apply_workflow`` call,
with the exact permission (write vs. submit) asserted right before each
call too, and the forbidden self-approval path proved rejected (document
state unchanged) rather than merely "not attempted".

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
class TestSalesOrderFinanceApprovalWorkflowBehavior(unittest.TestCase):
    CUSTOMER_NAME = "Easytouch Finance Approval Workflow Test Customer"
    ITEM_CODE = "EASYTOUCH-FINANCE-APPROVAL-TEST-SERVICE"
    OWNER_EMAIL = "owner@nasiib.example"
    FINANCE_APPROVER_EMAIL = "finance.approver@nasiib.example"
    LOW_VALUE_RATE = 3000  # grand_total <= 5000 threshold
    HIGH_VALUE_RATE = 8000  # grand_total > 5000 threshold

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
        cls.item_code = cls._ensure_service_item()

        # "Finance Approval" is a custom Role: it must exist (created by
        # the Role fixture) before the Workflow fixture that links to it
        # is imported.
        assert frappe.db.exists("Role", "Finance Approval"), (
            "The 'Finance Approval' Role fixture must be imported before "
            "the 'Sales Order Finance Approval' Workflow fixture."
        )

        cls.owner_user = cls._ensure_user(cls.OWNER_EMAIL, "Sales User")
        cls.finance_approver_user = cls._ensure_user(
            cls.FINANCE_APPROVER_EMAIL, "Finance Approval"
        )

        # A workflow role does not bypass ordinary DocType permissions on
        # linked masters a Sales Order save/submit must read (Customer,
        # Item, Company). Derive the minimal baseline role each actor
        # actually needs for each from *live* DocPerm metadata and assign
        # only that -- never widen the workflow role itself.
        cls._ensure_actor_can_read_dependencies(cls.owner_user, "Sales User")
        cls._ensure_actor_can_read_dependencies(
            cls.finance_approver_user, "Finance Approval"
        )

    @classmethod
    def tearDownClass(cls):
        cls.frappe.set_user("Administrator")

    # -- master-data setup (mirrors other authoritative test modules) ------

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
                "company_name": "Easytouch Finance Approval Test Co",
                "abbr": "EFAT",
                "default_currency": "USD",
                "country": "United States",
            }
        )
        company.insert(ignore_permissions=True)
        frappe.db.commit()
        return company.name

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

        from frappe.utils import add_years, get_first_day

        start = get_first_day(today).replace(month=1, day=1)
        end = add_years(start, 1)
        from datetime import timedelta

        end = end - timedelta(days=1)

        fy = frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": "Easytouch Finance Approval Test FY %s" % today,
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
                "customer_group_name": "Easytouch Finance Approval Test Group",
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
                "territory_name": "Easytouch Finance Approval Test Territory",
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
                    "item_group_name": "Easytouch Finance Approval Test Items",
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
        """Grant the minimal existing baseline role (derived from live
        DocPerm metadata) this actor needs to read the linked masters a
        Sales Order save/submit actually touches (Customer, Item,
        Company) -- never by widening the workflow role itself.
        """
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

    # -- document construction ----------------------------------------------

    def _make_sales_order(self, as_user, rate):
        frappe = self.frappe
        frappe.set_user(as_user)

        self.assertTrue(
            frappe.has_permission(doctype="Customer", doc=self.customer, ptype="read"),
            f"{as_user} must be able to read the Customer this order links.",
        )
        self.assertTrue(
            frappe.has_permission(doctype="Item", doc=self.item_code, ptype="read"),
            f"{as_user} must be able to read the Item this order links.",
        )

        today = frappe.utils.nowdate()
        order = frappe.get_doc(
            {
                "doctype": "Sales Order",
                "customer": self.customer,
                "company": self.company,
                "currency": self.company_currency,
                "conversion_rate": 1,
                "order_type": "Sales",
                "transaction_date": today,
                "delivery_date": today,
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 1,
                        "rate": rate,
                        "delivery_date": today,
                    }
                ],
            }
        )
        order.insert()
        frappe.db.commit()
        return order.name

    # -- behavior tests -------------------------------------------------------

    def test_low_value_order_is_self_submittable_by_sales_user(self):
        frappe = self.frappe
        from frappe.model.workflow import apply_workflow

        try:
            order_name = self._make_sales_order(
                self.owner_user, rate=self.LOW_VALUE_RATE
            )
            order = frappe.get_doc("Sales Order", order_name)
            self.assertEqual(order.workflow_state, "Draft")
            self.assertLessEqual(order.grand_total, 5000)

            frappe.set_user(self.owner_user)
            self.assertEqual(frappe.session.user, self.owner_user)
            self.assertIn("Sales User", frappe.get_roles(self.owner_user))
            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Order",
                    doc=order,
                    ptype="submit",
                    user=self.owner_user,
                ),
                "Sales User must hold live submit permission to execute "
                "the Draft -> Approved transition itself for a "
                "<=$5,000 order.",
            )

            apply_workflow(order, "Submit")
            frappe.db.commit()
        finally:
            frappe.set_user("Administrator")

        order = frappe.get_doc("Sales Order", order_name)
        self.assertEqual(order.workflow_state, "Approved")
        self.assertEqual(order.docstatus, 1)

    def test_high_value_order_cannot_be_self_approved_by_sales_user(self):
        frappe = self.frappe
        from frappe.model.workflow import apply_workflow

        try:
            order_name = self._make_sales_order(
                self.owner_user, rate=self.HIGH_VALUE_RATE
            )
            order = frappe.get_doc("Sales Order", order_name)
            self.assertEqual(order.workflow_state, "Draft")
            self.assertGreater(order.grand_total, 5000)

            frappe.set_user(self.owner_user)
            self.assertEqual(frappe.session.user, self.owner_user)
            self.assertIn("Sales User", frappe.get_roles(self.owner_user))

            # Denied: the owner must not self-submit a >$5,000 order --
            # the "Submit" transition's condition (grand_total <= 5000)
            # excludes it.
            with self.assertRaises(Exception):
                apply_workflow(frappe.get_doc("Sales Order", order_name), "Submit")
            unchanged = frappe.get_doc("Sales Order", order_name)
            self.assertEqual(unchanged.workflow_state, "Draft")
            self.assertEqual(unchanged.docstatus, 0)

            # Allowed: the owner can route it for finance approval (an
            # ordinary save -- live WRITE permission only).
            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Order",
                    doc=unchanged,
                    ptype="write",
                    user=self.owner_user,
                ),
                "Sales User must hold live write permission to route a "
                ">$5,000 order to Pending Finance Approval (an ordinary "
                "save, next docstatus=0).",
            )
            apply_workflow(unchanged, "Send for Finance Approval")
            frappe.db.commit()
        finally:
            frappe.set_user("Administrator")

        routed = frappe.get_doc("Sales Order", order_name)
        self.assertEqual(routed.workflow_state, "Pending Finance Approval")
        self.assertEqual(routed.docstatus, 0)

        # Denied: the owner (Sales User only) must not be able to approve
        # their own routed high-value order -- "Approve" is only allowed
        # for the "Finance Approval" role.
        try:
            frappe.set_user(self.owner_user)
            self.assertNotIn(
                "Finance Approval", frappe.get_roles(self.owner_user)
            )
            with self.assertRaises(Exception):
                apply_workflow(
                    frappe.get_doc("Sales Order", order_name), "Approve"
                )
            still_pending = frappe.get_doc("Sales Order", order_name)
            self.assertEqual(still_pending.workflow_state, "Pending Finance Approval")
            self.assertEqual(still_pending.docstatus, 0)
        finally:
            frappe.set_user("Administrator")

        # Allowed: a distinct user holding the "Finance Approval" role
        # can approve (submit) the routed order.
        try:
            frappe.set_user(self.finance_approver_user)
            self.assertEqual(frappe.session.user, self.finance_approver_user)
            self.assertIn(
                "Finance Approval", frappe.get_roles(self.finance_approver_user)
            )
            to_approve = frappe.get_doc("Sales Order", order_name)
            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Order",
                    doc=to_approve,
                    ptype="submit",
                    user=self.finance_approver_user,
                ),
                "Finance Approval must hold live submit permission to "
                "execute the Pending Finance Approval -> Approved "
                "transition for a >$5,000 order.",
            )
            apply_workflow(to_approve, "Approve")
            frappe.db.commit()
        finally:
            frappe.set_user("Administrator")

        approved = frappe.get_doc("Sales Order", order_name)
        self.assertEqual(approved.workflow_state, "Approved")
        self.assertEqual(approved.docstatus, 1)


if __name__ == "__main__":
    unittest.main()
