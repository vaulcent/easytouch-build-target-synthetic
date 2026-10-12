"""Authoritative ERPNext v16 behavior evidence for the "Sales Invoice
Discount Approval" Workflow requirement: a salesperson must not be able
to approve (submit) a Sales Invoice carrying a big discount themselves;
any discount above 10% must be routed to a Sales Manager for approval.

State / transition / permission matrix this test exercises end-to-end
against a real disposable ERPNext v16 site (see fixtures/workflow.json,
fixtures/workflow_state.json, fixtures/workflow_action_master.json, and
synthetic_build_target_app.synthetic_build_target_app.install
.ensure_discount_approval_workflow_permissions for the fixtures/installer
this proves):

    state                       docstatus  allow_edit role
    Draft                       0          Sales User
    Pending Manager Approval    0          Sales Manager
    Approved                    1          Sales Manager

    transition                                        allowed role   condition                              underlying live permission required
    Draft -> Approved            (action "Submit")     Sales User     additional_discount_percentage <= 10  SUBMIT on Sales Invoice (next docstatus=1)
    Draft -> Pending Mgr Appr.   (action "Send for Approval")  Sales User  additional_discount_percentage > 10   WRITE on Sales Invoice (next docstatus=0, ordinary save)
    Pending Mgr Appr. -> Approved(action "Approve")    Sales Manager  additional_discount_percentage > 10   SUBMIT on Sales Invoice (next docstatus=1)

Both the allowed and the denied paths are exercised as real, distinct
Frappe users/sessions, asserting ``frappe.session.user`` and
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
class TestSalesInvoiceDiscountApprovalWorkflowBehavior(unittest.TestCase):
    CUSTOMER_NAME = "Easytouch Discount Approval Workflow Test Customer"
    ITEM_CODE = "EASYTOUCH-DISCOUNT-APPROVAL-TEST-SERVICE"
    PRICE_LIST_NAME = "Easytouch Discount Approval Test Price List"
    SALESPERSON_EMAIL = "easytouch-discount-approval-salesperson@example.test"
    MANAGER_EMAIL = "easytouch-discount-approval-manager@example.test"

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
        cls.income_account = cls._ensure_income_account(cls.company)
        cls.item_code = cls._ensure_service_item()
        cls.price_list = cls._ensure_price_list(cls.company_currency)

        cls.salesperson_user = cls._ensure_user(cls.SALESPERSON_EMAIL, "Sales User")
        cls.manager_user = cls._ensure_user(cls.MANAGER_EMAIL, "Sales Manager")

        # A workflow role does not bypass ordinary DocType permissions on
        # linked masters a Sales Invoice save/submit must read (Customer,
        # Item, Account, Company). Derive the minimal baseline role each
        # actor actually needs for each from *live* DocPerm metadata and
        # assign only that -- never widen the workflow role itself.
        cls._ensure_actor_can_read_dependencies(cls.salesperson_user, "Sales User")
        cls._ensure_actor_can_read_dependencies(
            cls.manager_user, "Sales Manager"
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
                "company_name": "Easytouch Discount Approval Test Co",
                "abbr": "EDAT",
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

        fy = frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": "Easytouch Discount Approval Test FY %s" % today,
                "year_start_date": today,
                "year_end_date": today,
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
                "customer_group_name": "Easytouch Discount Approval Test Group",
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
                "territory_name": "Easytouch Discount Approval Test Territory",
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
                "account_name": "Easytouch Discount Approval Test Sales",
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
                    "item_group_name": "Easytouch Discount Approval Test Items",
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

    # -- behavior tests -------------------------------------------------------

    def test_low_discount_is_self_submittable_by_salesperson(self):
        frappe = self.frappe
        from frappe.model.workflow import apply_workflow

        try:
            invoice_name = self._make_sales_invoice(
                self.salesperson_user, discount_percentage=5
            )
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(invoice.workflow_state, "Draft")

            frappe.set_user(self.salesperson_user)
            self.assertEqual(frappe.session.user, self.salesperson_user)
            self.assertIn("Sales User", frappe.get_roles(self.salesperson_user))
            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Invoice",
                    doc=invoice,
                    ptype="submit",
                    user=self.salesperson_user,
                ),
                "Sales User must hold live submit permission to execute "
                "the Draft -> Approved transition itself for a <=10% "
                "discount invoice.",
            )

            apply_workflow(invoice, "Submit")
            frappe.db.commit()
        finally:
            frappe.set_user("Administrator")

        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(invoice.workflow_state, "Approved")
        self.assertEqual(invoice.docstatus, 1)

    def test_high_discount_cannot_be_self_approved_by_salesperson(self):
        frappe = self.frappe
        from frappe.model.workflow import apply_workflow

        try:
            invoice_name = self._make_sales_invoice(
                self.salesperson_user, discount_percentage=25
            )
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(invoice.workflow_state, "Draft")

            frappe.set_user(self.salesperson_user)
            self.assertEqual(frappe.session.user, self.salesperson_user)
            self.assertIn("Sales User", frappe.get_roles(self.salesperson_user))

            # Denied: the salesperson must not self-submit a >10% discount
            # invoice -- the "Submit" transition's condition
            # (additional_discount_percentage <= 10) excludes it.
            with self.assertRaises(Exception):
                apply_workflow(
                    frappe.get_doc("Sales Invoice", invoice_name), "Submit"
                )
            unchanged = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(unchanged.workflow_state, "Draft")
            self.assertEqual(unchanged.docstatus, 0)

            # Allowed: the salesperson can route it for manager approval
            # (an ordinary save -- live WRITE permission only).
            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Invoice",
                    doc=frappe.get_doc("Sales Invoice", invoice_name),
                    ptype="write",
                    user=self.salesperson_user,
                ),
                "Sales User needs only live write permission for the "
                "ordinary-save Draft -> Pending Manager Approval "
                "transition.",
            )
            apply_workflow(
                frappe.get_doc("Sales Invoice", invoice_name), "Send for Approval"
            )
            frappe.db.commit()

            pending = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(pending.workflow_state, "Pending Manager Approval")
            self.assertEqual(pending.docstatus, 0)

            # Denied again: the same salesperson must not approve their
            # own big-discount invoice once it is pending manager
            # approval -- "Approve" is only allowed for Sales Manager.
            self.assertNotIn(
                "Sales Manager", frappe.get_roles(self.salesperson_user)
            )
            with self.assertRaises(Exception):
                apply_workflow(
                    frappe.get_doc("Sales Invoice", invoice_name), "Approve"
                )
            still_pending = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertEqual(
                still_pending.workflow_state, "Pending Manager Approval"
            )
            self.assertEqual(still_pending.docstatus, 0)

            # Allowed: the manager (distinct real user/session, trusted
            # role) approves (submits) the big-discount invoice.
            frappe.set_user(self.manager_user)
            self.assertEqual(frappe.session.user, self.manager_user)
            self.assertIn("Sales Manager", frappe.get_roles(self.manager_user))
            manager_doc = frappe.get_doc("Sales Invoice", invoice_name)
            self.assertTrue(
                frappe.has_permission(
                    doctype="Sales Invoice",
                    doc=manager_doc,
                    ptype="submit",
                    user=self.manager_user,
                ),
                "Sales Manager must hold live submit permission to "
                "execute the Pending Manager Approval -> Approved "
                "transition.",
            )
            apply_workflow(manager_doc, "Approve")
            frappe.db.commit()
        finally:
            frappe.set_user("Administrator")

        approved = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(approved.workflow_state, "Approved")
        self.assertEqual(approved.docstatus, 1)


if __name__ == "__main__":
    unittest.main()
