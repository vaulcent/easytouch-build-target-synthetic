"""Authoritative ERPNext v16 behavior evidence for the "prevent submitting
a Sales Invoice when the selling rate is below valuation rate unless the
user holds an authorized override role" requirement.

Proves, against a real disposable ERPNext v16 site, both configured
validation lanes (see hooks.py ``doc_events["Sales Invoice"]`` and
synthetic_build_target_app.synthetic_build_target_app
.sales_invoice_validations), with the currency- and Sales-UOM-aware
comparison the requirement demands:

1. ``validate`` (save-time lane): a user without the "Sales Invoice Rate
   Override" role cannot even *save* a domestic (Company-currency,
   Stock-UOM) Sales Invoice whose item rate is below that item's real
   warehouse Bin valuation rate (the row's own ``valuation_rate`` is left
   empty, exactly as a manually keyed-in row would be, so the fallback Bin
   lookup by item_code + warehouse is what is actually exercised).
2. ``before_submit`` (submit-time lane), exercised with a FOREIGN-currency
   invoice (EUR) and a Sales UOM ("Box") whose ``conversion_factor`` (10,
   meaning ONE Box contains 10 Stock-UOM "Nos" units) is greater than 1:
   a row priced at 200 EUR has ``base_rate`` 600 USD (200 * conversion_rate
   3), which is above the raw USD 100 valuation_rate but BELOW the correct
   per-Sales-UOM floor of 1000 USD (100 * conversion_factor 10) -- an
   ordinary user without the override role is blocked from submitting it.
3. The same ordinary (non-override) user CAN submit a row priced at 400
   EUR (base_rate 1200, above the 1000 floor) for the same item/UOM/
   currency combination.
4. A user holding the "Sales Invoice Rate Override" role (provisioned by
   the idempotent Role fixture + granted a real baseline submit-capable
   role derived from live Sales Invoice DocType permission metadata) CAN
   submit the same below-floor 200 EUR row that blocks the ordinary user.

A real Currency Exchange record (EUR -> USD, rate 3) is seeded so the
foreign-currency conversion_rate used is backed by real exchange-rate
master data, not merely typed onto the invoice. Accounts Settings'
``allow_multi_currency_invoices_against_single_party_account`` is enabled
on this disposable site only (discarded with the site) so the EUR invoice
can post against the Company-currency receivable account without an
unrelated currency-mismatch error masking the rate-validation behavior
under test.

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
    EUR_PRICE_LIST_NAME = "Easytouch Rate Validation Test EUR Price List"
    BLOCKED_USER_EMAIL = "easytouch-rate-validation-blocked@example.test"
    OVERRIDE_USER_EMAIL = "easytouch-rate-validation-override@example.test"
    BOX_UOM = "Box"

    VALUATION_RATE = 100  # USD per Stock UOM (Nos), set via a real Bin.
    BELOW_VALUATION_SELLING_RATE = 50  # domestic (USD) below-valuation rate.

    # Foreign-currency + Sales-UOM scenario: conversion_factor is the
    # number of Stock-UOM ("Nos") units in ONE Sales-UOM ("Box") unit.
    BOX_CONVERSION_FACTOR = 10
    EUR_TO_USD_RATE = 3
    BLOCKED_EUR_RATE = 200  # base_rate 600 < floor 1000 -> blocked.
    ALLOWED_EUR_RATE = 400  # base_rate 1200 > floor 1000 -> allowed.

    @classmethod
    def setUpClass(cls):
        import frappe

        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        cls.frappe = frappe
        frappe.set_user("Administrator")

        cls._created_invoices = []

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
        cls.price_list = cls._ensure_price_list(
            cls.PRICE_LIST_NAME, cls.company_currency
        )
        cls.eur_price_list = cls._ensure_price_list(cls.EUR_PRICE_LIST_NAME, "EUR")

        # Establish a real, current warehouse Bin valuation_rate via a
        # real, submitted stock movement -- never hardcoded directly on
        # the Bin. This is Company-currency, per Stock UOM ("Nos").
        cls._ensure_valuation_rate_via_material_receipt()

        # A real "Box" Sales UOM for this item whose conversion_factor is
        # the number of Stock-UOM ("Nos") units in ONE Box -- greater
        # than 1 -- so the per-Sales-UOM valuation floor genuinely differs
        # from the raw per-Stock-UOM valuation_rate.
        cls._ensure_box_uom_on_item()

        # A real Currency Exchange master record backing the EUR -> USD
        # conversion_rate used below (not merely typed onto the invoice).
        cls._ensure_currency_exchange()

        # Allow the EUR invoice to post against the Company-currency
        # receivable account on this disposable site only.
        cls._ensure_multi_currency_against_single_party_account()

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

    def tearDown(self):
        """Clean up every invoice created by this test and every record
        any of its real on_submit handlers created for it (for example a
        Project created by the unrelated Sales-Invoice-to-Project
        automation hook, which also fires on every real submit) -- so
        later tests on this shared disposable site never see leftovers.
        Cancelling/deleting the invoice alone does not remove those
        handler-created linked records.
        """
        frappe = self.frappe
        frappe.set_user("Administrator")
        for invoice_name in list(self._created_invoices):
            if frappe.db.exists("Project", {"sales_invoice": invoice_name}):
                for project_name in frappe.get_all(
                    "Project",
                    filters={"sales_invoice": invoice_name},
                    pluck="name",
                ):
                    frappe.delete_doc(
                        "Project",
                        project_name,
                        force=True,
                        ignore_permissions=True,
                    )
            if frappe.db.exists("Sales Invoice", invoice_name):
                doc = frappe.get_doc("Sales Invoice", invoice_name)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc(
                    "Sales Invoice",
                    invoice_name,
                    force=True,
                    ignore_permissions=True,
                )
        self._created_invoices.clear()
        frappe.db.commit()

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
    def _ensure_price_list(cls, name, currency):
        frappe = cls.frappe
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
    def _ensure_box_uom_on_item(cls):
        """Give the test item a real "Box" Sales UOM whose
        conversion_factor (Stock-UOM units per ONE Sales-UOM unit) is 10
        -- i.e. one Box contains 10 Nos.
        """
        frappe = cls.frappe
        if not frappe.db.exists("UOM", cls.BOX_UOM):
            frappe.get_doc({"doctype": "UOM", "uom_name": cls.BOX_UOM}).insert(
                ignore_permissions=True
            )
        item = frappe.get_doc("Item", cls.item_code)
        has_box = any(
            row.uom == cls.BOX_UOM for row in (item.get("uoms") or [])
        )
        if not has_box:
            item.append(
                "uoms",
                {
                    "uom": cls.BOX_UOM,
                    "conversion_factor": cls.BOX_CONVERSION_FACTOR,
                },
            )
            item.save(ignore_permissions=True)
            frappe.db.commit()

    @classmethod
    def _ensure_currency_exchange(cls):
        """Seed a real Currency Exchange master record (EUR -> USD, rate
        3) backing the foreign-currency conversion_rate used below.
        """
        frappe = cls.frappe
        if not frappe.db.exists("Currency", "EUR"):
            frappe.get_doc(
                {
                    "doctype": "Currency",
                    "currency_name": "EUR",
                    "enabled": 1,
                }
            ).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Currency", "EUR", "enabled", 1)

        today = frappe.utils.nowdate()
        existing = frappe.get_all(
            "Currency Exchange",
            filters={
                "from_currency": "EUR",
                "to_currency": "USD",
                "date": today,
            },
            pluck="name",
            limit=1,
        )
        if existing:
            frappe.db.set_value(
                "Currency Exchange",
                existing[0],
                "exchange_rate",
                cls.EUR_TO_USD_RATE,
            )
        else:
            frappe.get_doc(
                {
                    "doctype": "Currency Exchange",
                    "date": today,
                    "from_currency": "EUR",
                    "to_currency": "USD",
                    "exchange_rate": cls.EUR_TO_USD_RATE,
                }
            ).insert(ignore_permissions=True)
        frappe.db.commit()

        confirmed = frappe.db.get_value(
            "Currency Exchange",
            {"from_currency": "EUR", "to_currency": "USD", "date": today},
            "exchange_rate",
        )
        assert confirmed and float(confirmed) == float(cls.EUR_TO_USD_RATE), (
            "setup must establish a real Currency Exchange EUR -> USD "
            "rate of %s" % cls.EUR_TO_USD_RATE
        )

    @classmethod
    def _ensure_multi_currency_against_single_party_account(cls):
        frappe = cls.frappe
        settings = frappe.get_single("Accounts Settings")
        if not settings.get("allow_multi_currency_invoices_against_single_party_account"):
            settings.allow_multi_currency_invoices_against_single_party_account = 1
            settings.save(ignore_permissions=True)
            frappe.db.commit()

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

    def _draft_domestic_invoice_below_valuation_rate(self):
        """Insert (as Administrator, who is exempt) a Draft Sales Invoice
        in Company currency, Stock UOM, whose selling ``rate`` is below
        the real warehouse Bin valuation rate established in setUpClass.
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
        self._created_invoices.append(invoice.name)
        return invoice.name

    def _draft_eur_box_invoice(self, eur_rate):
        """Insert (as Administrator, who is exempt) a Draft Sales Invoice
        in EUR, selling in "Box" Sales UOM (conversion_factor 10), at
        ``eur_rate`` EUR per Box.
        """
        frappe = self.frappe
        frappe.set_user("Administrator")
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.customer,
                "company": self.company,
                "currency": "EUR",
                "conversion_rate": self.EUR_TO_USD_RATE,
                "selling_price_list": self.eur_price_list,
                "price_list_currency": "EUR",
                "plc_conversion_rate": self.EUR_TO_USD_RATE,
                "posting_date": frappe.utils.nowdate(),
                "due_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": self.item_code,
                        "qty": 1,
                        "uom": self.BOX_UOM,
                        "conversion_factor": self.BOX_CONVERSION_FACTOR,
                        "rate": eur_rate,
                        "warehouse": self.warehouse,
                        "income_account": self.income_account,
                    }
                ],
            }
        )
        invoice.insert(ignore_permissions=True)
        frappe.db.commit()
        self._created_invoices.append(invoice.name)
        return invoice

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
        invoice_name = self._draft_domestic_invoice_below_valuation_rate()
        try:
            frappe.set_user(self.blocked_user)
            self.assertNotIn(OVERRIDE_ROLE, frappe.get_roles(self.blocked_user))
            invoice = frappe.get_doc("Sales Invoice", invoice_name)
            with self.assertRaises(frappe.exceptions.ValidationError):
                invoice.submit()
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice_name, "docstatus"), 0
        )

    def test_foreign_currency_box_uom_row_below_floor_is_blocked_for_ordinary_user(
        self,
    ):
        """EUR 200/Box row: raw rate (200) is above the raw USD
        valuation_rate (100) and base_rate (600) is also above the raw
        valuation_rate (100) -- but base_rate (600) is BELOW the correct
        per-Sales-UOM (Box) floor of 1000 (valuation_rate 100 *
        conversion_factor 10, i.e. USD 60 per Stock UOM is below USD 100
        per Stock UOM). An ordinary, non-override user must be blocked.
        """
        frappe = self.frappe
        invoice = self._draft_eur_box_invoice(self.BLOCKED_EUR_RATE)
        row = invoice.items[0]

        raw_rate = float(row.rate)
        base_rate = float(row.base_rate)
        conversion_factor = float(row.conversion_factor)
        valuation_floor_per_box = self.VALUATION_RATE * conversion_factor

        self.assertEqual(raw_rate, 200)
        self.assertEqual(base_rate, 600)
        self.assertEqual(conversion_factor, self.BOX_CONVERSION_FACTOR)
        self.assertGreater(raw_rate, self.VALUATION_RATE)
        self.assertGreater(base_rate, self.VALUATION_RATE)
        self.assertEqual(valuation_floor_per_box, 1000)
        self.assertLess(base_rate, valuation_floor_per_box)
        self.assertLess(base_rate / conversion_factor, self.VALUATION_RATE)

        try:
            frappe.set_user(self.blocked_user)
            self.assertNotIn(OVERRIDE_ROLE, frappe.get_roles(self.blocked_user))
            reloaded = frappe.get_doc("Sales Invoice", invoice.name)
            with self.assertRaises(frappe.exceptions.ValidationError):
                reloaded.submit()
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 0
        )

    def test_foreign_currency_box_uom_row_above_floor_submits_for_ordinary_user(
        self,
    ):
        """EUR 400/Box row: base_rate (1200) is above the 1000 floor
        (USD 120 per Stock UOM is above USD 100 per Stock UOM); the same
        ordinary, non-override user must be able to submit it.
        """
        frappe = self.frappe
        invoice = self._draft_eur_box_invoice(self.ALLOWED_EUR_RATE)
        row = invoice.items[0]

        base_rate = float(row.base_rate)
        conversion_factor = float(row.conversion_factor)
        valuation_floor_per_box = self.VALUATION_RATE * conversion_factor

        self.assertEqual(base_rate, 1200)
        self.assertEqual(valuation_floor_per_box, 1000)
        self.assertGreater(base_rate, valuation_floor_per_box)
        self.assertGreater(base_rate / conversion_factor, self.VALUATION_RATE)

        try:
            frappe.set_user(self.blocked_user)
            self.assertNotIn(OVERRIDE_ROLE, frappe.get_roles(self.blocked_user))
            reloaded = frappe.get_doc("Sales Invoice", invoice.name)
            reloaded.submit()
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 1
        )

    def test_override_user_can_submit_foreign_currency_below_floor_row(self):
        """The same below-floor 200 EUR/Box row that blocks the ordinary
        user CAN be submitted by a user holding the override role."""
        frappe = self.frappe
        invoice = self._draft_eur_box_invoice(self.BLOCKED_EUR_RATE)
        row = invoice.items[0]
        base_rate = float(row.base_rate)
        conversion_factor = float(row.conversion_factor)
        self.assertLess(base_rate, self.VALUATION_RATE * conversion_factor)

        try:
            frappe.set_user(self.override_user)
            self.assertIn(OVERRIDE_ROLE, frappe.get_roles(self.override_user))
            reloaded = frappe.get_doc("Sales Invoice", invoice.name)
            reloaded.submit()
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 1
        )


if __name__ == "__main__":
    unittest.main()
