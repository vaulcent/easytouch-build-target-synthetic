"""Authoritative ERPNext v16 behavior evidence for the "prevent submitting
a Sales Invoice when the selling rate is below valuation rate unless the
user holds an authorized override role" requirement.

Proves, against a real disposable ERPNext v16 site, both configured
validation lanes (see hooks.py ``doc_events["Sales Invoice"]`` and
synthetic_build_target_app.synthetic_build_target_app
.sales_invoice_validations):

1. ``validate`` (save-time lane): a user without the "Sales Invoice Rate
   Override" role cannot even *save* a Sales Invoice whose item rate is
   below that item's real warehouse Bin valuation rate (the row's own
   ``valuation_rate`` is left empty, exactly as a manually keyed-in row
   would be, so the fallback Bin lookup by item_code + warehouse is what
   is actually exercised).
2. ``before_submit`` (submit-time lane): a user without the override role
   cannot *submit* an already-saved Sales Invoice at a below-valuation
   rate either -- the attempt is rejected and the document's docstatus
   stays unchanged.
3. A user holding the "Sales Invoice Rate Override" role (provisioned by
   the idempotent Role fixture + granted a real baseline submit-capable
   role derived from live Sales Invoice DocType permission metadata) CAN
   submit the same below-valuation-rate invoice.

Loaded by ``bench execute`` with an active Frappe database context: reuses
``frappe.local.db`` when already present, and only initializes from
``frappe.local.site`` when needed. Skips only when Frappe itself is
unavailable in this local coding sandbox.
"""

from __future__ import annotations

import importlib.util
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("validate",)

FRAPPE_AVAILABLE = importlib.util.find_spec("frappe") is not None

OVERRIDE_ROLE = "Sales Invoice Rate Override"


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; this authoritative "
    "case must run inside a real disposable ERPNext v16 site via "
    "bench execute.",
)
class TestSalesInvoiceRateValidationBehavior(unittest.TestCase):
    CUSTOMER_NAME = "Easytouch Rate Validation Behavior Test Customer"
    ITEM_CODE = "EASYTOUCH-RATE-VALIDATION-TEST-ITEM"
    PRICE_LIST_NAME = "Easytouch Rate Validation Test Price List"
    BLOCKED_USER_EMAIL = "easytouch-rate-validation-blocked@example.test"
    OVERRIDE_USER_EMAIL = "easytouch-rate-validation-override@example.test"

    VALUATION_RATE = 100
    BELOW_VALUATION_SELLING_RATE = 50

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
        cls.warehouse = cls._ensure_warehouse(cls.company)
        cls.customer_group = cls._ensure_leaf_customer_group()
        cls.territory = cls._ensure_leaf_territory()
        cls.customer = cls._ensure_customer()
        cls.income_account = cls._ensure_income_account(cls.company)
        cls.item_code = cls._ensure_stock_item()
        cls.price_list = cls._ensure_price_list(cls.company_currency)

        # Establish a real, current warehouse Bin valuation_rate via a
        # real, submitted stock movement -- never hardcoded directly on
        # the Bin.
        cls._ensure_valuation_rate_via_material_receipt()

        cls.submit_capable_role = cls._submit_capable_role()
        cls.blocked_user = cls._ensure_user(
            cls.BLOCKED_USER_EMAIL, [cls.submit_capable_role]
        )
        cls.override_user = cls._ensure_user(
            cls.OVERRIDE_USER_EMAIL, [cls.submit_capable_role, OVERRIDE_ROLE]
        )

    @classmethod
    def tearDownClass(cls):
        cls.frappe.set_user("Administrator")

    # -- master-data setup -------------------------------------------------

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
                "company_name": "Easytouch Rate Validation Test Co",
                "abbr": "ERVT",
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
                "warehouse_name": "Easytouch Rate Validation Test Store",
                "company": company,
            }
        )
        warehouse.insert(ignore_permissions=True)
        frappe.db.commit()
        return warehouse.name

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
                "year": "Easytouch Rate Validation Test FY %s" % today,
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
                "customer_group_name": "Easytouch Rate Validation Test Group",
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
                "territory_name": "Easytouch Rate Validation Test Territory",
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
                "account_name": "Easytouch Rate Validation Test Sales",
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
        root_name = (
            root[0]
            if root
            else frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "All Item Groups",
                    "is_group": 1,
                }
            )
            .insert(ignore_permissions=True)
            .name
        )
        leaf_doc = frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": "Easytouch Rate Validation Test Items",
                "is_group": 0,
                "parent_item_group": root_name,
            }
        )
        leaf_doc.insert(ignore_permissions=True)
        return leaf_doc.name

    @classmethod
    def _ensure_stock_item(cls):
        frappe = cls.frappe
        code = cls.ITEM_CODE
        if frappe.db.exists("Item", code):
            return code
        item_group_name = cls._ensure_item_group()
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
                "is_stock_item": 1,
            }
        )
        item.insert(ignore_permissions=True)
        return item.name

    @classmethod
    def _ensure_valuation_rate_via_material_receipt(cls):
        frappe = cls.frappe
        current = frappe.db.get_value(
            "Bin",
            {"item_code": cls.item_code, "warehouse": cls.warehouse},
            "valuation_rate",
        )
        if current and float(current) == float(cls.VALUATION_RATE):
            return
        receipt = frappe.get_doc(
            {
                "doctype": "Stock Entry",
                "stock_entry_type": "Material Receipt",
                "purpose": "Material Receipt",
                "company": cls.company,
                "posting_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": cls.item_code,
                        "qty": 10,
                        "t_warehouse": cls.warehouse,
                        "basic_rate": cls.VALUATION_RATE,
                    }
                ],
            }
        )
        receipt.insert(ignore_permissions=True)
        receipt.submit()
        frappe.db.commit()

        actual = frappe.db.get_value(
            "Bin",
            {"item_code": cls.item_code, "warehouse": cls.warehouse},
            "valuation_rate",
        )
        assert actual and float(actual) == float(cls.VALUATION_RATE), (
            "setup must establish a real warehouse Bin valuation_rate of "
            "%s via a real submitted Stock Entry" % cls.VALUATION_RATE
        )

    @classmethod
    def _submit_capable_role(cls):
        frappe = cls.frappe
        meta = frappe.get_meta("Sales Invoice")
        candidates = sorted(
            {
                perm.role
                for perm in meta.permissions
                if (perm.permlevel or 0) == 0
                and perm.submit
                and perm.role not in ("All", "Guest")
            }
        )
        assert candidates, (
            "live Sales Invoice DocType permission metadata must grant "
            "submit to at least one standard role"
        )
        return "Accounts User" if "Accounts User" in candidates else candidates[0]

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
                    "enabled": 1,
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

    # -- document construction ----------------------------------------------

    def _draft_invoice_below_valuation_rate(self):
        """Insert (as Administrator, who is exempt) a Draft Sales Invoice
        whose single item's own ``valuation_rate`` is left empty and
        whose selling ``rate`` is below the real warehouse Bin valuation
        rate established in setUpClass.
        """
        frappe = self.frappe
        frappe.set_user("Administrator")
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
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 1,
                        "rate": self.BELOW_VALUATION_SELLING_RATE,
                        "warehouse": self.warehouse,
                        "income_account": self.income_account,
                    }
                ],
            }
        )
        invoice.insert(ignore_permissions=True)
        frappe.db.commit()
        return invoice.name

    # -- behavior tests -------------------------------------------------------

    def test_validate_lane_blocks_save_below_valuation_rate_without_override(self):
        """The 'validate' (save-time) lane rejects even an ordinary save
        at a below-valuation rate for a user without the override role --
        exercising the real Bin-fallback lookup, not a hardcoded value."""
        frappe = self.frappe
        try:
            frappe.set_user(self.blocked_user)
            self.assertNotIn(OVERRIDE_ROLE, frappe.get_roles(self.blocked_user))

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
                    "items": [
                        {
                            "item_code": self.item_code,
                            "qty": 1,
                            "rate": self.BELOW_VALUATION_SELLING_RATE,
                            "warehouse": self.warehouse,
                            "income_account": self.income_account,
                        }
                    ],
                }
            )
            with self.assertRaises(frappe.exceptions.ValidationError):
                invoice.insert(ignore_permissions=True)
        finally:
            frappe.set_user("Administrator")

    def test_before_submit_lane_blocks_submission_without_override(self):
        frappe = self.frappe
        invoice_name = self._draft_invoice_below_valuation_rate()
        try:
            frappe.set_user(self.blocked_user)
            self.assertNotIn(OVERRIDE_ROLE, frappe.get_roles(self.blocked_user))
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            with self.assertRaises(frappe.exceptions.ValidationError):
                invoice.submit()
        finally:
            frappe.set_user("Administrator")

        unchanged = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(unchanged.docstatus, 0)

    def test_override_role_user_can_submit_below_valuation_rate(self):
        frappe = self.frappe
        invoice_name = self._draft_invoice_below_valuation_rate()
        try:
            frappe.set_user(self.override_user)
            self.assertIn(OVERRIDE_ROLE, frappe.get_roles(self.override_user))
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            invoice.submit()
            frappe.db.commit()
        finally:
            frappe.set_user("Administrator")

        submitted = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(submitted.docstatus, 1)


if __name__ == "__main__":
    unittest.main()
