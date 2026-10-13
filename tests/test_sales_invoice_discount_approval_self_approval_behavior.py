"""Authoritative ERPNext v16 behavior evidence that the "Sales Invoice
Discount Approval" Workflow's manager-approval step is independent of
its requester: the approving ("Approve", Pending Manager Approval ->
Approved) Workflow Transition's ``allow_self_approval`` is 0 (see
fixtures/workflow.json), so even a user who holds BOTH the initiating
role (Sales User) and the approving role (Sales Manager) cannot
actually apply that transition on an invoice they themselves own --
``apply_workflow`` denies it with ERPNext's own ``frappe.ValidationError``
and the invoice remains unchanged -- while a distinct user holding only
the Sales Manager role can.

Per ERPNext v16's real ``frappe.model.workflow.get_transitions``
implementation, self-approval independence is enforced inside
``apply_workflow`` itself, not by filtering the action out of
``get_transitions``'s returned list (a role match alone is enough for an
action to be *listed* there). This module therefore asserts the actual
enforcement point -- ``apply_workflow`` raising ``frappe.ValidationError``
and the document staying at "Pending Manager Approval" / docstatus 0 --
rather than asserting anything about which actions ``get_transitions``
lists.

This is a compact, dedicated module for this one requirement (the
self-approval independence of the >10% discount manager-approval step)
layered on top of the existing "Sales Invoice Discount Approval"
Workflow fixture exercised more broadly by
tests/test_sales_invoice_discount_approval_workflow_behavior.py. It does
not duplicate that module's full state/transition coverage.

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
class TestSalesInvoiceDiscountApprovalSelfApprovalBehavior(unittest.TestCase):
    CUSTOMER_NAME = "Easytouch Discount Self Approval Test Customer"
    ITEM_CODE = "EASYTOUCH-DISCOUNT-SELF-APPROVAL-TEST-SERVICE"
    PRICE_LIST_NAME = "Easytouch Discount Self Approval Test Price List"
    OWNER_MANAGER_EMAIL = "easytouch-discount-self-approval-owner-manager@example.test"
    OTHER_MANAGER_EMAIL = "easytouch-discount-self-approval-other-manager@example.test"

    @classmethod
    def setUpClass(cls):
        import frappe

        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        cls.frappe = frappe
        frappe.set_user("Administrator")

        workflow = frappe.get_doc(
            "Workflow", "Sales Invoice Discount Approval"
        )
        approve_transition = next(
            row
            for row in workflow.transitions
            if row.action == "Approve" and row.state == "Pending Manager Approval"
        )
        assert int(approve_transition.allow_self_approval or 0) == 0, (
            "The 'Approve' transition (Pending Manager Approval -> "
            "Approved) must have allow_self_approval = 0 so the manager "
            "approval step is independent of its requester."
        )

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
        cls.price_list = cls._ensure_price_list(cls.company_currency)

        # The invoice owner holds BOTH the initiating role (Sales User)
        # and the approving role (Sales Manager).
        cls.owner_manager_user = cls._ensure_user(
            cls.OWNER_MANAGER_EMAIL, ["Sales User", "Sales Manager"]
        )
        # A distinct user holds only the approving role.
        cls.other_manager_user = cls._ensure_user(
            cls.OTHER_MANAGER_EMAIL, ["Sales Manager"]
        )

        for user in (cls.owner_manager_user, cls.other_manager_user):
            cls._ensure_actor_can_read_dependencies(user, "Sales User")
            cls._ensure_actor_can_read_dependencies(user, "Sales Manager")

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
                "company_name": "Easytouch Discount Self Approval Test Co",
                "abbr": "EDSA",
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
                "year": "Easytouch Discount Self Approval Test FY %s" % today,
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
                "customer_group_name": "Easytouch Discount Self Approval Test Group",
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
                "territory_name": "Easytouch Discount Self Approval Test Territory",
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
                "account_name": "Easytouch Discount Self Approval Test Sales",
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
                    "item_group_name": "Easytouch Discount Self Approval Test Items",
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
    def _ensure_user(cls, email, roles):
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
        changed = False
        for role in roles:
            if role not in existing_roles:
                user.append("roles", {"role": role})
                changed = True
        if changed:
            user.save(ignore_permissions=True)
        frappe.db.commit()
        return user.name

    @classmethod
    def _ensure_actor_can_read_dependencies(cls, user, workflow_role):
        """Grant the minimal existing baseline role (derived from live
        DocPerm metadata) this actor needs to read the linked masters a
        Sales Invoice save/submit actually touches (Customer, Item,
        Account, Company) -- never by widening the workflow role itself.
        """
        frappe = cls.frappe
        for doctype in ("Customer", "Item", "Account", "Company"):
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

    def _make_sales_invoice(self, as_user, discount_percentage):
        frappe = self.frappe
        frappe.set_user(as_user)

        self.assertTrue(
            frappe.has_permission(doctype="Customer", doc=self.customer, ptype="read"),
            f"{as_user} must be able to read the Customer this invoice links.",
        )
        self.assertTrue(
            frappe.has_permission(doctype="Item", doc=self.item_code, ptype="read"),
            f"{as_user} must be able to read the Item this invoice links.",
        )

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
                "apply_discount_on": "Grand Total",
                "additional_discount_percentage": discount_percentage,
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 1,
                        "rate": 1000,
                        "income_account": self.income_account,
                    }
                ],
            }
        )
        invoice.insert()
        frappe.db.commit()
        return invoice.name

    # -- behavior test --------------------------------------------------------

    def test_owner_holding_both_roles_cannot_self_approve_but_other_manager_can(self):
        frappe = self.frappe
        from frappe.model.workflow import apply_workflow

        try:
            invoice_name = self._make_sales_invoice(
                self.owner_manager_user, discount_percentage=30
            )
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(invoice.owner, self.owner_manager_user)
            self.assertEqual(invoice.workflow_state, "Draft")

            frappe.set_user(self.owner_manager_user)
            self.assertEqual(frappe.session.user, self.owner_manager_user)
            owner_roles = frappe.get_roles(self.owner_manager_user)
            self.assertIn("Sales User", owner_roles)
            self.assertIn("Sales Manager", owner_roles)

            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Invoice",
                    doc=invoice,
                    ptype="write",
                    user=self.owner_manager_user,
                ),
                "Sales User must hold live write permission to route a "
                ">10% discount invoice to Pending Manager Approval (an "
                "ordinary save, next docstatus=0).",
            )
            apply_workflow(invoice, "Send for Approval")
            frappe.db.commit()

            routed = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(routed.workflow_state, "Pending Manager Approval")
            self.assertEqual(routed.docstatus, 0)

            # The owner also holds the approving "Sales Manager" role,
            # but allow_self_approval = 0 on the "Approve" transition
            # means ERPNext's real apply_workflow must still deny the
            # invoice owner's own attempt to apply it -- self-approval
            # independence is enforced inside apply_workflow itself, not
            # by filtering the action out of get_transitions.
            self.assertEqual(frappe.session.user, self.owner_manager_user)
            with self.assertRaises(frappe.ValidationError):
                apply_workflow(
                    frappe.get_doc("Sales Invoice", invoice_name), "Approve"
                )

            still_pending = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(
                still_pending.workflow_state, "Pending Manager Approval"
            )
            self.assertEqual(still_pending.docstatus, 0)
        finally:
            frappe.set_user("Administrator")

        # A distinct user holding only the "Sales Manager" role (not the
        # invoice owner, and not holding "Sales User") must be able to
        # apply the same "Approve" transition successfully.
        try:
            frappe.set_user(self.other_manager_user)
            self.assertEqual(frappe.session.user, self.other_manager_user)
            other_roles = frappe.get_roles(self.other_manager_user)
            self.assertIn("Sales Manager", other_roles)
            self.assertNotIn("Sales User", other_roles)
            self.assertNotEqual(self.other_manager_user, self.owner_manager_user)

            pending = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertNotEqual(pending.owner, self.other_manager_user)
            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Invoice",
                    doc=pending,
                    ptype="submit",
                    user=self.other_manager_user,
                ),
                "Sales Manager must hold live submit permission to "
                "execute the Pending Manager Approval -> Approved "
                "transition (next docstatus=1, a real submit).",
            )

            approved = apply_workflow(pending, "Approve")
            frappe.db.commit()

            self.assertEqual(approved.workflow_state, "Approved")
            self.assertEqual(approved.docstatus, 1)

            final = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(final.workflow_state, "Approved")
            self.assertEqual(final.docstatus, 1)
        finally:
            frappe.set_user("Administrator")
            # Clean up: cancel the now-submitted invoice and delete it so
            # no stale linked record (and no Project created by the
            # unrelated Sales Invoice -> Project on_submit hook) survives
            # this test for a later test to mistake as its own.
            final_doc = frappe.get_doc("Sales Invoice", invoice_name)
            if final_doc.docstatus == 1:
                final_doc.cancel()
                frappe.db.commit()
            linked_projects = frappe.get_all(
                "Project",
                filters={"sales_invoice": invoice_name},
                pluck="name",
            )
            for project_name in linked_projects:
                frappe.delete_doc(
                    "Project", project_name, ignore_permissions=True, force=True
                )
            frappe.delete_doc(
                "Sales Invoice", invoice_name, ignore_permissions=True, force=True
            )
            frappe.db.commit()
