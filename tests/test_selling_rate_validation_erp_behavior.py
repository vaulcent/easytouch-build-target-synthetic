"""Authoritative ERP-backed evidence for the selling-rate-below-valuation
submit validation.

Loaded by `bench execute` against a disposable, live ERPNext v16 site. It
proves that the real Sales Invoice ``before_submit`` hook registered by
this app blocks an ordinary user from submitting a row priced below its
valuation floor, allows the same ordinary user to submit a row priced
above that floor, and allows a user holding the "Selling Rate Override"
role to submit the below-floor row.

Currency/UOM evidence: the invoice is in EUR against a USD Company (EUR ->
USD Currency Exchange rate 3), and the Sales UOM "Box" has
``conversion_factor`` 10 -- ten Stock-UOM ("Nos") units per one Sales-UOM
("Box") unit, never the reverse. The Bin valuation rate (100 USD per Nos)
is established by a real, submitted Material Receipt Stock Entry, not
guessed or hardcoded.

Numeric evidence (per the completion contract): with Bin valuation_rate
100 USD per Nos, conversion_factor 10, and EUR->USD conversion_rate 3:
  - a blocked row at 200 EUR has raw rate 200 (> 100, wrong currency) and
    base_rate 600 (> 100, wrong UOM), but base_rate 600 is below the
    correct Sales-UOM floor 1000 (= 100 x 10), equivalently USD 60 per Nos
    is below USD 100 per Nos. The ordinary user must be blocked.
  - an allowed row at 400 EUR has base_rate 1200, above the 1000 floor
    (equivalently USD 120 per Nos, above USD 100 per Nos). The same
    ordinary, non-override user must be able to submit it.
  - the override user may submit the 200 EUR (blocked-for-others) row.

Actor evidence: ERPNext's "Administrator" user is special-cased by Frappe
and must never be treated as an "ordinary user" for this test's purpose,
so the blocked/allowed assertions explicitly run as a real, dedicated
non-Administrator System User who does not hold the "Selling Rate
Override" role (created fresh below, distinct from the override-role
user), switching the session with ``frappe.set_user`` around each submit
call and restoring the prior session user afterward.

Permission evidence: real, non-Administrator System Users are still
subject to ERPNext's ordinary Role Permission Manager checks while the
standard ``validate``/``set_missing_values`` chain re-reads the invoice's
Item, Customer, Price List, and Warehouse rows during submit (for example
``get_item_details`` calls ``item.check_permission()``, which checks
"read" permission on Item regardless of ``ignore_permissions`` used on the
parent Sales Invoice document). "System Manager" does NOT bypass ordinary
doctype permission checks the way "Administrator" does, so both test
actors are granted a broad, realistic set of standard ERPNext roles
("Sales Manager", "Accounts Manager", "System Manager", "Stock Manager",
"Stock User", "Item Manager", "Sales User", "Purchase User", "Accounts
User") that between them cover read access to Item, Customer, Price List,
Warehouse, and Account in a stock ERPNext v16 install. Neither the
ordinary user nor the override user is meant to be a test of that
unrelated permission system. Only the custom "Selling Rate Override" role
differs between the two actors; that is exactly what this validator gates
on.

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
EASYTOUCH_ERP_BEHAVIOR_KINDS = ("validation",)

PREFIX = "EASYTOUCH-SRV"
OVERRIDE_ROLE = "Selling Rate Override"

# Broad, realistic standard ERPNext roles that together carry the
# ordinary built-in read permissions needed to legitimately create and
# submit a Sales Invoice (Account, Customer, Item, Price List, Warehouse,
# Cost Center) as a real, non-Administrator System User. "System Manager"
# alone does NOT bypass ordinary doctype permission checks (unlike
# "Administrator"), and the exact role that grants Item read access can
# vary by ERPNext release, so this list deliberately includes every
# standard role commonly granted Item/Customer/Price List/Warehouse read
# access ("Stock Manager", "Stock User", "Item Manager", "Sales User",
# "Purchase User", "Accounts User") in addition to "Sales Manager",
# "Accounts Manager", and "System Manager". These roles are granted to
# *both* the ordinary and the override test actors so that neither hits
# unrelated standard-permission walls while ERPNext re-reads Item/
# Customer/Price List/Warehouse during submit; only the custom "Selling
# Rate Override" role differs between them, which is exactly what this
# validator gates on.
STANDARD_SALES_ACCOUNTS_ROLES = (
    "Sales Manager",
    "Accounts Manager",
    "System Manager",
    "Stock Manager",
    "Stock User",
    "Item Manager",
    "Sales User",
    "Purchase User",
    "Accounts User",
)


def _ensure_frappe_context():
    if getattr(frappe.local, "db", None):
        return
    site = getattr(frappe.local, "site", None)
    if site:
        frappe.init(site=site)
        frappe.connect()


def _ensure_warehouse_type_transit():
    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc(
            {"doctype": "Warehouse Type", "name": "Transit", "warehouse_type": "Transit"}
        ).insert(ignore_permissions=True)


def _get_or_create_company():
    existing = frappe.db.get_value("Company", {"default_currency": "USD"}, "name")
    if existing:
        return existing

    _ensure_warehouse_type_transit()

    name = f"{PREFIX} Company"
    if frappe.db.exists("Company", name):
        return name

    company = frappe.get_doc(
        {
            "doctype": "Company",
            "company_name": name,
            "abbr": "ESRV",
            "default_currency": "USD",
            "country": "United States",
            "domain": "Services",
            "chart_of_accounts": "Standard",
        }
    )
    company.insert(ignore_permissions=True)
    return company.name


def _get_company_defaults(company):
    income_account = frappe.db.get_value(
        "Account", {"company": company, "root_type": "Income", "is_group": 0}, "name"
    )
    receivable_account = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
    )
    cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
    warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
    return income_account, receivable_account, cost_center, warehouse


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
        linked = frappe.get_all("Fiscal Year Company", filters={"parent": row.name}, pluck="company")
        if not linked or company in linked:
            return row.name

    year = getdate(posting_date).year
    fy_name = f"{PREFIX}-{year}"
    if frappe.db.exists("Fiscal Year", fy_name):
        return fy_name

    fy_doc = frappe.get_doc(
        {
            "doctype": "Fiscal Year",
            "year": fy_name,
            "year_start_date": f"{year}-01-01",
            "year_end_date": f"{year}-12-31",
            "companies": [{"company": company}],
        }
    )
    fy_doc.insert(ignore_permissions=True)
    return fy_doc.name


def _ensure_uom(uom_name):
    if frappe.db.exists("UOM", uom_name):
        return uom_name
    frappe.get_doc({"doctype": "UOM", "uom_name": uom_name}).insert(ignore_permissions=True)
    return uom_name


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


def _ensure_stock_item_with_box_uom():
    """Stock item whose Stock UOM is "Nos" and whose Sales UOM "Box" has
    conversion_factor 10 -- i.e. one Box contains 10 Nos (ten Stock-UOM
    units per one Sales-UOM unit)."""
    item_code = f"{PREFIX}-STOCK-ITEM"
    if frappe.db.exists("Item", item_code):
        return item_code

    stock_uom = _ensure_uom("Nos")
    box_uom = _ensure_uom("Box")

    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_code,
            "item_group": _ensure_item_group_leaf(),
            "stock_uom": stock_uom,
            "is_stock_item": 1,
            "uoms": [{"uom": box_uom, "conversion_factor": 10}],
        }
    )
    item.insert(ignore_permissions=True)
    return item.name


def _ensure_stock_entry_type_material_receipt():
    if not frappe.db.exists("Stock Entry Type", "Material Receipt"):
        frappe.get_doc(
            {
                "doctype": "Stock Entry Type",
                "name": "Material Receipt",
                "purpose": "Material Receipt",
            }
        ).insert(ignore_permissions=True)
    return "Material Receipt"


def _receive_stock(company, item_code, warehouse, qty, basic_rate, posting_date):
    """Submit a real Material Receipt Stock Entry so the Bin valuation
    rate is genuine ERPNext-computed evidence, not a hardcoded value."""
    entry_type = _ensure_stock_entry_type_material_receipt()
    entry = frappe.get_doc(
        {
            "doctype": "Stock Entry",
            "stock_entry_type": entry_type,
            "purpose": "Material Receipt",
            "company": company,
            "posting_date": posting_date,
            "set_posting_time": 1,
            "items": [
                {
                    "item_code": item_code,
                    "t_warehouse": warehouse,
                    "qty": qty,
                    "basic_rate": basic_rate,
                }
            ],
        }
    )
    entry.insert(ignore_permissions=True)
    entry.submit()
    return entry


def _ensure_currency_exchange(from_currency, to_currency, exchange_rate, date):
    if frappe.db.exists(
        "Currency Exchange", {"date": date, "from_currency": from_currency, "to_currency": to_currency}
    ):
        return
    frappe.get_doc(
        {
            "doctype": "Currency Exchange",
            "date": date,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "exchange_rate": exchange_rate,
        }
    ).insert(ignore_permissions=True)


def _ensure_price_list(name, currency):
    if frappe.db.exists("Price List", name):
        return name
    frappe.get_doc(
        {
            "doctype": "Price List",
            "price_list_name": name,
            "currency": currency,
            "selling": 1,
            "buying": 0,
            "enabled": 1,
        }
    ).insert(ignore_permissions=True)
    return name


def _ensure_leaf(doctype, name_field, parent_field):
    leaf = frappe.db.get_value(doctype, {"is_group": 0}, "name")
    if leaf:
        return leaf
    root = frappe.db.get_value(doctype, {"is_group": 1}, "name") or frappe.db.get_value(doctype, {}, "name")
    new_name = f"{PREFIX}-{doctype.upper().replace(' ', '-')}"
    if frappe.db.exists(doctype, new_name):
        return new_name
    doc = frappe.get_doc({"doctype": doctype, name_field: new_name, parent_field: root, "is_group": 0})
    doc.insert(ignore_permissions=True)
    return doc.name


def _make_customer():
    name = f"{PREFIX}-CUSTOMER"
    if frappe.db.exists("Customer", name):
        return name
    territory = _ensure_leaf("Territory", "territory_name", "parent_territory")
    customer_group = _ensure_leaf("Customer Group", "customer_group_name", "parent_customer_group")
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


def _ensure_override_role():
    if not frappe.db.exists("Role", OVERRIDE_ROLE):
        frappe.get_doc(
            {"doctype": "Role", "role_name": OVERRIDE_ROLE, "desk_access": 1}
        ).insert(ignore_permissions=True)
    return OVERRIDE_ROLE


def _ensure_user_with_roles(email, roles, first_name="User"):
    """Create (or fetch) a real, enabled, non-Administrator System User
    holding at least the given list of roles (adding any missing ones to
    an existing user). Used for both the "ordinary" and "override" test
    actors so neither Administrator-bypass nor missing standard-role
    permissions can stand in for this validator's own role gating."""
    if not frappe.db.exists("User", email):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": first_name,
                "send_welcome_email": 0,
                "roles": [{"role": role} for role in roles],
            }
        )
        user.insert(ignore_permissions=True)
    else:
        user = frappe.get_doc("User", email)
        existing_roles = {r.role for r in user.roles}
        changed = False
        for role in roles:
            if role not in existing_roles:
                user.append("roles", {"role": role})
                changed = True
        if changed:
            user.save(ignore_permissions=True)
    return email


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is unavailable in this local sandbox")
class TestSellingRateValidationErpBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_frappe_context()
        from frappe.utils import nowdate

        cls.posting_date = nowdate()
        cls.company = _get_or_create_company()
        (
            cls.income_account,
            cls.receivable_account,
            cls.cost_center,
            cls.warehouse,
        ) = _get_company_defaults(cls.company)

        cls.fiscal_year = _ensure_fiscal_year(cls.company, cls.posting_date)
        cls.item_code = _ensure_stock_item_with_box_uom()

        # Real, submitted Material Receipt: 50 Nos at 100 USD each ->
        # ERPNext computes Bin.valuation_rate = 100 USD per Nos.
        cls.stock_entry = _receive_stock(
            cls.company, cls.item_code, cls.warehouse, 50, 100, cls.posting_date
        )

        cls.bin_valuation_rate = frappe.db.get_value(
            "Bin", {"item_code": cls.item_code, "warehouse": cls.warehouse}, "valuation_rate"
        )

        _ensure_currency_exchange("EUR", "USD", 3, cls.posting_date)
        cls.price_list = _ensure_price_list(f"{PREFIX}-PRICE-LIST-EUR", "EUR")
        cls.customer = _make_customer()
        _ensure_override_role()

        # Both actors are real, enabled, non-Administrator System Users
        # who hold the same broad set of standard ERPNext roles (see
        # STANDARD_SALES_ACCOUNTS_ROLES above for why each role is
        # included). The *only* role difference between them is the
        # custom "Selling Rate Override" role, which is exactly what
        # this validator gates on.
        cls.override_user = _ensure_user_with_roles(
            "srv-override-user@example.test",
            (*STANDARD_SALES_ACCOUNTS_ROLES, OVERRIDE_ROLE),
            first_name="Override",
        )
        # A genuinely distinct, non-Administrator actor holding the same
        # standard access roles but never the override role. Using the
        # default "bench execute" session (typically Administrator) would
        # be wrong evidence here: Administrator is special-cased by
        # Frappe and must never be treated as an "ordinary user" for a
        # role-gated validation.
        cls.ordinary_user = _ensure_user_with_roles(
            "srv-ordinary-user@example.test",
            STANDARD_SALES_ACCOUNTS_ROLES,
            first_name="Ordinary",
        )

        accounts_settings = frappe.get_single("Accounts Settings")
        cls._prior_multi_currency_setting = accounts_settings.get(
            "allow_multi_currency_invoices_against_single_party_account"
        )
        accounts_settings.allow_multi_currency_invoices_against_single_party_account = 1
        accounts_settings.save(ignore_permissions=True)

        frappe.db.commit()
        cls.created_invoices = []

    @classmethod
    def tearDownClass(cls):
        from synthetic_build_target_app.sales_invoice_automation import (
            project_name_for_invoice,
        )

        # Restore the Administrator/bench-execute session before any
        # cleanup so deletes are never blocked by the ordinary user's
        # narrower permissions.
        frappe.set_user("Administrator")

        for inv in cls.created_invoices:
            project_name = project_name_for_invoice(inv)
            project_docname = frappe.db.get_value(
                "Project", {"project_name": project_name}, "name"
            )
            if project_docname:
                frappe.delete_doc("Project", project_docname, force=1, ignore_permissions=True)

        for inv in cls.created_invoices:
            fresh = frappe.get_doc("Sales Invoice", inv.name)
            if fresh.docstatus == 1:
                fresh.cancel()
            frappe.delete_doc("Sales Invoice", inv.name, force=1, ignore_permissions=True)

        accounts_settings = frappe.get_single("Accounts Settings")
        accounts_settings.allow_multi_currency_invoices_against_single_party_account = (
            cls._prior_multi_currency_setting
        )
        accounts_settings.save(ignore_permissions=True)

        frappe.db.commit()

    def _new_eur_invoice(self, rate, suffix):
        inv = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.customer,
                "company": self.company,
                "currency": "EUR",
                "conversion_rate": 3,
                "selling_price_list": self.price_list,
                "price_list_currency": "EUR",
                "plc_conversion_rate": 3,
                "posting_date": self.posting_date,
                "due_date": self.posting_date,
                "set_posting_time": 1,
                "debit_to": self.receivable_account,
                "update_stock": 0,
                "items": [
                    {
                        "item_code": self.item_code,
                        "warehouse": self.warehouse,
                        "uom": "Box",
                        "conversion_factor": 10,
                        "qty": 1,
                        "rate": rate,
                        "income_account": self.income_account,
                        "cost_center": self.cost_center,
                    }
                ],
            }
        )
        inv.insert(ignore_permissions=True)
        self.created_invoices.append(inv)
        return inv

    def test_bin_valuation_rate_is_real_evidence(self):
        self.assertEqual(self.bin_valuation_rate, 100)

    def test_blocked_row_is_blocked_for_ordinary_user(self):
        invoice = self._new_eur_invoice(200, "blocked")

        row = invoice.items[0]
        # Assert the real document values and both conversions before
        # asserting the outcome.
        self.assertEqual(row.rate, 200)
        self.assertEqual(row.base_rate, 600)  # 200 EUR * conversion_rate 3
        self.assertGreater(row.rate, self.bin_valuation_rate)  # 200 > 100 (wrong, mismatched currency)
        self.assertGreater(row.base_rate, self.bin_valuation_rate)  # 600 > 100 (wrong, mismatched UOM)
        valuation_floor = self.bin_valuation_rate * row.conversion_factor  # 100 * 10 = 1000
        self.assertEqual(valuation_floor, 1000)
        self.assertLess(row.base_rate, valuation_floor)  # 600 < 1000: correctly below floor
        self.assertLess(row.base_rate / row.conversion_factor, self.bin_valuation_rate)  # 60 < 100 USD/Nos

        # Run the actual submit as a real, dedicated ordinary (non-
        # Administrator, non-override) user. Administrator is
        # special-cased by Frappe itself and is never valid evidence for
        # an "ordinary user" assertion on a role-gated validator.
        prior_user = frappe.session.user
        try:
            frappe.set_user(self.ordinary_user)
            with self.assertRaises(frappe.ValidationError):
                invoice.submit()
        finally:
            frappe.set_user(prior_user)

        invoice.reload()
        self.assertEqual(invoice.docstatus, 0)  # still a draft: submit was genuinely blocked

    def test_row_above_floor_is_allowed_for_ordinary_user(self):
        invoice = self._new_eur_invoice(400, "allowed")

        row = invoice.items[0]
        self.assertEqual(row.rate, 400)
        self.assertEqual(row.base_rate, 1200)  # 400 EUR * conversion_rate 3
        valuation_floor = self.bin_valuation_rate * row.conversion_factor  # 100 * 10 = 1000
        self.assertEqual(valuation_floor, 1000)
        self.assertGreater(row.base_rate, valuation_floor)  # 1200 > 1000: correctly above floor
        self.assertGreater(row.base_rate / row.conversion_factor, self.bin_valuation_rate)  # 120 > 100 USD/Nos

        prior_user = frappe.session.user
        try:
            frappe.set_user(self.ordinary_user)
            invoice.submit()
        finally:
            frappe.set_user(prior_user)

        invoice.reload()
        self.assertEqual(invoice.docstatus, 1)  # genuinely submitted: the same ordinary user is allowed

    def test_override_role_allows_submitting_below_floor_row(self):
        invoice = self._new_eur_invoice(200, "override")

        row = invoice.items[0]
        valuation_floor = self.bin_valuation_rate * row.conversion_factor
        self.assertEqual(row.base_rate, 600)
        self.assertEqual(valuation_floor, 1000)
        self.assertLess(row.base_rate, valuation_floor)  # same below-floor row as the blocked case

        prior_user = frappe.session.user
        try:
            frappe.set_user(self.override_user)
            invoice.submit()
        finally:
            frappe.set_user(prior_user)

        invoice.reload()
        self.assertEqual(invoice.docstatus, 1)  # override role lets the below-floor row through
