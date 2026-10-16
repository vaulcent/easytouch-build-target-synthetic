"""Authoritative ERP-behavior evidence for the Sales Invoice selling-rate-
vs-valuation-rate validation.

Requirement: create server-side validation that prevents submitting a
Sales Invoice when the selling rate is below valuation rate unless the
user has an authorized override role ("Selling Rate Override"). The
validation is implemented as the Sales Invoice ``validate`` hook
registered in synthetic_build_target_app/hooks.py, pointing at
synthetic_build_target_app.sales_invoice_rate_validation.
validate_selling_rate_against_valuation.

This module is loaded by `bench execute` with an active Frappe database
context against a real, disposable ERPNext v16 validation site. Frappe is
unavailable in the local coding sandbox, so these cases skipUnless Frappe
can be imported locally; they are not skipped, and must execute, once run
inside an installed ERPNext site.

Currency / UOM scenario (per the completion contract): Bin valuation_rate
is 100 USD per Stock UOM; the Sales UOM "Box" has conversion_factor 10,
meaning ONE Box contains 10 Nos (ten Stock-UOM units per one Sales-UOM
unit) -- never the other way round. A real Currency Exchange record seeds
EUR -> USD at 3. A blocked row at rate=200 EUR has raw rate 200 (above the
bare valuation 100, but in the wrong currency to compare) and base_rate
200*3=600 (above 100, but still the wrong UOM to compare); the correct
Sales-UOM floor is valuation_rate * conversion_factor = 100*10 = 1000, and
600 < 1000, so the ordinary (non-override) user must be blocked. An
allowed row at rate=400 EUR has base_rate 400*3=1200 >= 1000 and must
submit successfully for the same ordinary user. The below-floor 200 EUR
row must submit successfully for a user holding the "Selling Rate
Override" role.

The pre-existing Sales Invoice -> Project on_submit automation
(synthetic_build_target_app.sales_invoice_events) is untouched and will
fire on every real submit exercised here; every Project it creates is
tracked and deleted in tearDown before the invoice is cancelled/deleted,
per the completion contract (cancel/delete of the invoice does not remove
a Project the hook created).

Permission note: ERPNext's own ``get_item_details`` call (invoked from
``Sales Invoice.set_missing_item_details`` during ``validate``) always
calls ``item.check_permission()`` for the real *acting session user* --
even though the Sales Invoice document insert itself runs with
``ignore_permissions=True``. ``ignore_permissions`` only bypasses the
permission check on the Sales Invoice document being saved; it has no
effect on this nested, independent Item-read permission check performed
inside ERPNext's own pricing/item-detail logic. "Accounts Manager" alone
does not carry standard ERPNext Item-doctype read permission, so both
test users below are also given the "Sales User" role, which does carry
it, in addition to whatever finance/override roles the scenario needs.
Standard Role-based DocType permissions only ever apply to a System User
with desk access, so the user fixture also always forces
``user_type = "System User"`` and ``enabled = 1`` on every reuse -- not
only when first inserting the User -- instead of merely appending roles
onto whatever user_type the record already has.

Shared-actor note: this app's authoritative test suites run together on
the same disposable site and some of them (per approved workspace memory,
e.g. owner-dashboard fixtures) may already create/reuse the
"owner@nasiib.example" actor as a plain portal/Website User before this
module runs; the user fixture below repairs that on every reuse too.
"""
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("VALIDATION",)

try:
    import frappe  # noqa: F401
    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False


if FRAPPE_AVAILABLE:
    from tests.test_sales_invoice_project_automation import (
        _ensure_connection,
        _get_or_create_company,
        _get_or_create_customer,
        _get_or_create_fiscal_year,
        _get_or_create_item_group,
        _get_or_create_uom,
        _get_income_account,
        _get_cost_center,
        _get_or_create_selling_price_list,
    )
    from synthetic_build_target_app.sales_invoice_events import build_project_name
    from synthetic_build_target_app.sales_invoice_rate_validation import OVERRIDE_ROLE


VALUATION_RATE = 100  # USD, per Stock UOM
CONVERSION_FACTOR = 10  # Stock-UOM units (Nos) per ONE Sales-UOM unit (Box)
EUR_TO_USD_RATE = 3

# "Sales User" is the standard ERPNext role that carries real Item-doctype
# read permission; it is required on every test actor below because
# ERPNext's own get_item_details() checks Item read permission for the
# acting session user regardless of ignore_permissions on the Sales
# Invoice document itself (see module docstring).
ITEM_READ_ROLE = "Sales User"


def _ensure_warehouse(company):
    import frappe

    name = "Selling Rate Test Warehouse - {0}".format(
        frappe.get_cached_value("Company", company, "abbr")
    )
    if frappe.db.exists("Warehouse", name):
        return name
    warehouse = frappe.get_doc({
        "doctype": "Warehouse",
        "warehouse_name": "Selling Rate Test Warehouse",
        "company": company,
    })
    warehouse.insert(ignore_permissions=True)
    return warehouse.name


def _ensure_box_uom():
    import frappe

    if frappe.db.exists("UOM", "Selling Rate Test Box"):
        return "Selling Rate Test Box"
    uom = frappe.get_doc({"doctype": "UOM", "uom_name": "Selling Rate Test Box"})
    uom.insert(ignore_permissions=True)
    return uom.name


def _get_or_create_stock_item(stock_uom, box_uom):
    import frappe

    code = "SELLING-RATE-TEST-ITEM"
    if frappe.db.exists("Item", code):
        return code
    item = frappe.get_doc({
        "doctype": "Item",
        "item_code": code,
        "item_name": code,
        "item_group": _get_or_create_item_group(),
        "stock_uom": stock_uom,
        "is_stock_item": 1,
        "uoms": [{"uom": box_uom, "conversion_factor": CONVERSION_FACTOR}],
    })
    item.insert(ignore_permissions=True)
    return item.name


def _set_bin_valuation_rate(item_code, warehouse, valuation_rate):
    import frappe

    bin_name = frappe.db.get_value(
        "Bin", {"item_code": item_code, "warehouse": warehouse}, "name"
    )
    if bin_name:
        frappe.db.set_value("Bin", bin_name, "valuation_rate", valuation_rate)
        return

    bin_doc = frappe.get_doc({
        "doctype": "Bin",
        "item_code": item_code,
        "warehouse": warehouse,
        "valuation_rate": valuation_rate,
        "actual_qty": 0,
    })
    bin_doc.insert(ignore_permissions=True)


def _ensure_currency_exchange():
    import frappe
    from frappe.utils import nowdate

    if not frappe.db.exists("Currency", "EUR"):
        frappe.get_doc({"doctype": "Currency", "currency_name": "EUR"}).insert(
            ignore_permissions=True
        )
    frappe.db.set_value("Currency", "EUR", "enabled", 1)

    today = nowdate()
    existing = frappe.db.exists(
        "Currency Exchange",
        {"date": today, "from_currency": "EUR", "to_currency": "USD"},
    )
    if existing:
        frappe.db.set_value("Currency Exchange", existing, "exchange_rate", EUR_TO_USD_RATE)
        return
    doc = frappe.get_doc({
        "doctype": "Currency Exchange",
        "date": today,
        "from_currency": "EUR",
        "to_currency": "USD",
        "exchange_rate": EUR_TO_USD_RATE,
    })
    doc.insert(ignore_permissions=True)


def _allow_multi_currency_single_party_account():
    import frappe

    settings = frappe.get_single("Accounts Settings")
    settings.allow_multi_currency_invoices_against_single_party_account = 1
    settings.save(ignore_permissions=True)


def _get_or_create_user(email, roles):
    """Return a System User with desk access that holds ``roles``.

    This actor may already exist on the shared disposable validation
    site (created by a different authoritative test module in this app,
    e.g. an owner-dashboard fixture) with ``user_type`` set to something
    other than "System User", or with desk access disabled. Standard
    Role-based DocType permissions -- needed here because ERPNext's own
    ``get_item_details`` call checks real Item read permission for the
    acting session user even while the Sales Invoice document insert
    itself runs with ``ignore_permissions=True`` -- only ever apply to a
    System User with desk access. So both ``user_type`` and ``enabled``
    are forced on every call, not only when the User is first inserted,
    and the document is always saved (not only when new roles were
    appended) so a pre-existing non-System user is actually repaired.
    """
    import frappe

    if frappe.db.exists("User", email):
        user = frappe.get_doc("User", email)
    else:
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": email.split("@")[0],
            "send_welcome_email": 0,
        })
        user.insert(ignore_permissions=True)

    user.user_type = "System User"
    user.enabled = 1

    existing_roles = {r.role for r in user.get("roles") or []}
    for role in roles:
        if role not in existing_roles:
            user.append("roles", {"role": role})

    user.save(ignore_permissions=True)
    frappe.clear_cache(user=user.name)
    return user.name


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class SalesInvoiceSellingRateValidationTests(unittest.TestCase):
    """Proves the Sales Invoice selling-rate-vs-valuation-rate validation
    on a real, disposable ERPNext v16 site."""

    @classmethod
    def setUpClass(cls):
        _ensure_connection()
        import frappe

        cls.company = _get_or_create_company()
        cls.warehouse = _ensure_warehouse(cls.company)
        cls.stock_uom = _get_or_create_uom()
        cls.box_uom = _ensure_box_uom()
        cls.item_code = _get_or_create_stock_item(cls.stock_uom, cls.box_uom)
        _set_bin_valuation_rate(cls.item_code, cls.warehouse, VALUATION_RATE)

        cls.income_account = _get_income_account(cls.company)
        cls.cost_center = _get_cost_center(cls.company)
        cls.customer = _get_or_create_customer("Selling Rate Validation Customer")

        _get_or_create_fiscal_year(cls.company)
        _ensure_currency_exchange()
        _allow_multi_currency_single_party_account()

        cls.ordinary_user = _get_or_create_user(
            "selling-rate-ordinary-user@nasiib.example",
            roles=["Accounts Manager", ITEM_READ_ROLE],
        )
        cls.override_user = _get_or_create_user(
            "owner@nasiib.example",
            roles=["Accounts Manager", ITEM_READ_ROLE, OVERRIDE_ROLE],
        )

        # Sanity-check the Item-read permission fixture itself before any
        # test relies on it implicitly via Sales Invoice validate(): a
        # PermissionError here would otherwise surface deep inside
        # ERPNext's own get_item_details() call stack instead of at the
        # fixture that is actually responsible for it.
        frappe.set_user(cls.ordinary_user)
        frappe.clear_cache(user=cls.ordinary_user)
        assert frappe.has_permission("Item", "read", user=cls.ordinary_user), (
            "ordinary_user fixture must hold real Item read permission"
        )
        frappe.set_user(cls.override_user)
        frappe.clear_cache(user=cls.override_user)
        assert frappe.has_permission("Item", "read", user=cls.override_user), (
            "override_user fixture must hold real Item read permission"
        )

        cls._created_invoices = []
        cls._created_projects = []
        frappe.set_user("Administrator")
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        import frappe

        frappe.set_user("Administrator")

        # Delete handler-created Projects BEFORE touching invoices: the
        # existing Sales Invoice on_submit automation creates a Project per
        # submitted invoice, and cancelling/deleting the invoice does not
        # remove that Project.
        for project_doc_name in cls._created_projects:
            if frappe.db.exists("Project", project_doc_name):
                frappe.delete_doc(
                    "Project", project_doc_name, force=True, ignore_permissions=True
                )

        for invoice_name in cls._created_invoices:
            if frappe.db.exists("Sales Invoice", invoice_name):
                si = frappe.get_doc("Sales Invoice", invoice_name)
                if si.docstatus == 1:
                    si.cancel()
                frappe.delete_doc(
                    "Sales Invoice", invoice_name, force=True, ignore_permissions=True
                )

        frappe.db.commit()

    def _track_invoice(self, invoice_name):
        type(self)._created_invoices.append(invoice_name)

    def _track_project_for_invoice(self, invoice_doc):
        project_name = build_project_name(invoice_doc)
        project_doc_name = __import__("frappe").db.get_value(
            "Project", {"project_name": project_name}, "name"
        )
        if project_doc_name:
            type(self)._created_projects.append(project_doc_name)

    def _build_invoice(self, rate, as_user):
        import frappe
        from frappe.utils import nowdate

        frappe.set_user(as_user)
        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": self.customer,
            "company": self.company,
            "currency": "EUR",
            "conversion_rate": EUR_TO_USD_RATE,
            "posting_date": nowdate(),
            "due_date": nowdate(),
            "items": [{
                "item_code": self.item_code,
                "qty": 1,
                "rate": rate,
                "uom": self.box_uom,
                "conversion_factor": CONVERSION_FACTOR,
                "warehouse": self.warehouse,
                "income_account": self.income_account,
                "cost_center": self.cost_center,
            }],
        })
        return si

    def test_below_floor_row_computed_values_and_ordinary_user_is_blocked(self):
        import frappe

        si = self._build_invoice(rate=200, as_user=self.ordinary_user)
        si.calculate_taxes_and_totals()
        row = si.items[0]

        # Assert the actual computed document values before asserting the
        # outcome, distinguishing both conversions.
        self.assertEqual(row.rate, 200)
        self.assertEqual(row.base_rate, 600)  # 200 EUR * conversion_rate 3
        self.assertGreater(row.rate, VALUATION_RATE)  # 200 > 100 (different currency)
        self.assertGreater(row.base_rate, VALUATION_RATE)  # 600 > 100 (different UOM)
        floor_per_sales_uom = VALUATION_RATE * CONVERSION_FACTOR
        self.assertEqual(floor_per_sales_uom, 1000)
        self.assertLess(row.base_rate, floor_per_sales_uom)  # 600 < 1000 -> blocked
        self.assertLess(row.base_rate / row.conversion_factor, VALUATION_RATE)  # 60 < 100

        frappe.set_user(self.ordinary_user)
        with self.assertRaises(frappe.exceptions.ValidationError):
            si.insert(ignore_permissions=True)
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def test_above_floor_row_submits_for_ordinary_user(self):
        import frappe

        si = self._build_invoice(rate=400, as_user=self.ordinary_user)
        si.calculate_taxes_and_totals()
        row = si.items[0]
        floor_per_sales_uom = VALUATION_RATE * CONVERSION_FACTOR

        self.assertEqual(row.base_rate, 1200)  # 400 EUR * conversion_rate 3
        self.assertGreaterEqual(row.base_rate, floor_per_sales_uom)  # 1200 >= 1000

        si.insert(ignore_permissions=True)
        self._track_invoice(si.name)
        si.submit()
        self._track_project_for_invoice(si)
        frappe.db.commit()

        self.assertEqual(si.docstatus, 1)

    def test_below_floor_row_submits_for_user_with_override_role(self):
        import frappe

        si = self._build_invoice(rate=200, as_user=self.override_user)
        si.calculate_taxes_and_totals()
        row = si.items[0]
        floor_per_sales_uom = VALUATION_RATE * CONVERSION_FACTOR
        self.assertEqual(row.base_rate, 600)
        self.assertLess(row.base_rate, floor_per_sales_uom)  # still below floor

        self.assertIn(
            OVERRIDE_ROLE, frappe.get_roles(self.override_user),
            "Override user must actually hold the Selling Rate Override role",
        )

        si.insert(ignore_permissions=True)
        self._track_invoice(si.name)
        si.submit()
        self._track_project_for_invoice(si)
        frappe.db.commit()

        self.assertEqual(si.docstatus, 1)


if __name__ == "__main__":
    unittest.main()
