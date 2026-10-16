"""Authoritative ERP-behavior evidence for the Sales Order
discount-approval Workflow.

Requirement: salespeople must not be able to approve big discounts
themselves. If a Sales Order's discount is more than 10%, it must be sent
to a Sales Manager for approval instead of being submittable directly by
the salesperson.

Implemented as the "Sales Order Discount Approval" Workflow fixture
(synthetic_build_target_app/fixtures/workflow.json, registered in
hooks.py's ``fixtures`` list) against the standard ERPNext ``Sales
Order`` field ``additional_discount_percentage``:

* Draft (docstatus 0) -- "Submit" -> Approved (docstatus 1), allowed role
  "Sales User", condition ``additional_discount_percentage <= 10``. An
  ordinary self-submit; ``allow_self_approval`` is left at its default.
* Draft (docstatus 0) -- "Send for Approval" -> Pending Manager Approval
  (docstatus 0), allowed role "Sales User", condition
  ``additional_discount_percentage > 10``.
* Pending Manager Approval (docstatus 0) -- "Approve" -> Approved
  (docstatus 1), allowed role "Sales Manager", condition
  ``additional_discount_percentage > 10``, and critically
  ``allow_self_approval = 0`` -- the approval must be independent of its
  requester.

Ordinary DocType permission, derived from live metadata, not assumed
---------------------------------------------------------------------
A workflow "allowed" role string is never, by itself, proof of real
DocType permission. Both workflow transitions above perform a real
docstatus 0 -> 1 submit (Draft -> Approved and Pending Manager Approval
-> Approved), so this test derives the actual role(s) that satisfy
read/write/create/submit on Sales Order straight from live Custom DocPerm
metadata (``frappe.get_meta("Sales Order").permissions``) in setUpClass,
asserts that "Sales User" and "Sales Manager" are among those derived
roles, and only then uses those exact role names to build the test
actors. That live grant is installed idempotently by deployable app
lifecycle code (synthetic_build_target_app.
sales_order_discount_workflow_permissions.
ensure_discount_approval_permissions, wired into hooks.py's
``after_migrate``) during the normal bench migrate lifecycle -- this test
module only *derives and asserts* that those permissions are present
(once in setUpClass, and again immediately before every ``apply_workflow``
call below); it never calls the installer or grants permissions itself.

Linked-master read permission for the Approve transition's real submit
------------------------------------------------------------------------
The "Approve" transition performs a genuine ERPNext ``doc.submit()`` on
the Sales Order, which runs the full accounts-controller validate
pipeline -- including ``set_missing_item_details`` /
``get_item_details``, which independently calls ``item.check_permission()``
for the real *acting session user*, regardless of the Sales Order's own
Sales Order DocType permission. This is the same nested, independent
Item-read permission check documented in
``tests/test_sales_invoice_selling_rate_validation.py``: "Sales Manager"
alone does not carry standard ERPNext Item-doctype read permission, so
the independent manager actor below is also given the existing baseline
"Sales User" role (derived from live Item DocPerm metadata, the same way
the Sales Order role matrix is derived), in addition to "Sales Manager" --
an existing baseline role grant, never a speculative widening of the
"Sales Manager" role or an unrelated Custom DocPerm addition. The owning
salesperson actor already holds "Sales User" as its initiating role, so
it already carries this Item-read permission.

Currency correctness
---------------------
Every Sales Order built here explicitly sets ``currency``,
``conversion_rate = 1``, ``selling_price_list`` (currency-matched via the
shared ``_get_or_create_selling_price_list`` helper), ``price_list_currency``
and ``plc_conversion_rate = 1`` to the real default currency of the test
Company (never a hardcoded second currency), so ERPNext never needs to
resolve a live Currency Exchange rate while pricing items for this
discount-approval workflow -- that concern is orthogonal to the
requirement under test here (which is about discount percentage, not
multi-currency conversion) and is already covered by a dedicated
multi-currency behavior module elsewhere in this app.

This module is loaded by `bench execute` with an active Frappe database
context against a real, disposable ERPNext v16 validation site. Frappe is
unavailable in the local coding sandbox, so these cases skipUnless Frappe
can be imported locally; they are not skipped, and must execute, once run
inside an installed ERPNext site.
"""
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('workflow',)

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
        _get_or_create_item,
        _get_or_create_selling_price_list,
    )
    from tests.test_sales_invoice_selling_rate_validation import _get_or_create_user


WORKFLOW_NAME = "Sales Order Discount Approval"

# Actor who both creates (owns) the high-discount order AND, for the
# self-approval-denial scenario, also holds the manager-level role --
# per the completion contract's explicit self-approval matrix ("Test with
# the invoice owner holding both the initiating and approver roles").
OWNER_USER = "owner@nasiib.example"
# A distinct, independent manager who does NOT own the order under test,
# used to prove the real (non-self) approval path succeeds.
INDEPENDENT_MANAGER_USER = "discount-workflow-manager@nasiib.example"

# Required live permission every acting role below must actually carry on
# Sales Order, derived from the workflow's own transition matrix: both the
# salesperson self-submit (Draft -> Approved) and the manager Approve
# (Pending Manager Approval -> Approved) transitions perform a real
# docstatus 0 -> 1 submit.
REQUIRED_SALES_ORDER_PERMISSIONS = {"read": 1, "write": 1, "create": 1, "submit": 1}

# The "Approve" transition's real doc.submit() independently runs
# ERPNext's own get_item_details(), which checks real Item-doctype read
# permission for the acting session user. Derived (and asserted) from
# live Item DocPerm metadata below, the same way the Sales Order role
# matrix is derived -- never assumed.
REQUIRED_ITEM_PERMISSIONS = {"read": 1}


def _derive_roles_with_required_permissions(doctype, required):
    """Inspect LIVE DocType permission metadata
    (``frappe.get_meta(doctype).permissions``, which reflects the real,
    installed combination of standard + Custom DocPerm rows) and return
    the set of permlevel-0 roles that actually carry every permission in
    ``required``.

    A Workflow Transition's ``allowed`` role string is never, by itself,
    evidence of real DocType permission -- this helper derives the
    genuinely-permitted role(s) from metadata instead of assuming the
    workflow's configured role name is also a valid document permission
    grant.
    """
    import frappe

    meta = frappe.get_meta(doctype)
    qualifying_roles = set()
    for perm in meta.permissions:
        if (perm.permlevel or 0) != 0:
            continue
        if all(getattr(perm, field, 0) for field in required):
            qualifying_roles.add(perm.role)
    return qualifying_roles


def _get_or_create_discount_order_customer():
    return _get_or_create_customer("Discount Workflow Customer")


def _build_sales_order(customer, company, item_code, discount_percentage, as_user):
    import frappe
    from frappe.utils import nowdate

    # Pin currency/price-list to the Company's own real default currency
    # so ERPNext never needs a live Currency Exchange rate while pricing
    # items here -- this workflow is about the discount percentage, not
    # multi-currency conversion.
    company_currency = frappe.get_cached_value("Company", company, "default_currency")
    price_list = _get_or_create_selling_price_list(company_currency)

    frappe.set_user(as_user)
    so = frappe.get_doc({
        "doctype": "Sales Order",
        "customer": customer,
        "company": company,
        "currency": company_currency,
        "conversion_rate": 1,
        "selling_price_list": price_list,
        "price_list_currency": company_currency,
        "plc_conversion_rate": 1,
        "transaction_date": nowdate(),
        "delivery_date": nowdate(),
        "apply_discount_on": "Grand Total",
        "additional_discount_percentage": discount_percentage,
        "items": [{
            "item_code": item_code,
            "qty": 1,
            "rate": 1000,
            "delivery_date": nowdate(),
        }],
    })
    so.insert()
    return so


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in this local sandbox")
class SalesOrderDiscountApprovalWorkflowTests(unittest.TestCase):
    """Proves the Sales Order discount-approval Workflow on a real,
    disposable ERPNext v16 site."""

    @classmethod
    def setUpClass(cls):
        _ensure_connection()
        import frappe

        assert frappe.db.exists("Workflow", WORKFLOW_NAME), (
            "The '{0}' Workflow fixture must be installed by the normal "
            "bench migrate/fixtures-sync lifecycle before this test runs."
        ).format(WORKFLOW_NAME)
        workflow_is_active = frappe.db.get_value("Workflow", WORKFLOW_NAME, "is_active")
        assert workflow_is_active, "The Sales Order discount-approval Workflow must be active."

        # Derive the real, permission-metadata-backed roles for the
        # salesperson and manager actors instead of simply trusting the
        # Workflow transitions' configured "allowed" role strings. This
        # must reflect the live installed grant from after_migrate
        # (ensure_discount_approval_permissions), not a value this test
        # invents or installs itself.
        qualifying_roles = _derive_roles_with_required_permissions(
            "Sales Order", REQUIRED_SALES_ORDER_PERMISSIONS
        )
        assert "Sales User" in qualifying_roles, (
            "Live Sales Order DocPerm metadata must grant 'Sales User' "
            "read/write/create/submit (installed by after_migrate's "
            "ensure_discount_approval_permissions) before the salesperson "
            "self-submit transition can be exercised. Derived qualifying "
            "roles were: {0}".format(sorted(qualifying_roles))
        )
        assert "Sales Manager" in qualifying_roles, (
            "Live Sales Order DocPerm metadata must grant 'Sales Manager' "
            "read/write/create/submit (installed by after_migrate's "
            "ensure_discount_approval_permissions) before the manager "
            "Approve transition can be exercised. Derived qualifying "
            "roles were: {0}".format(sorted(qualifying_roles))
        )
        cls.salesperson_role = "Sales User"
        cls.manager_role = "Sales Manager"

        # The "Approve" transition performs a real doc.submit(), which
        # independently runs get_item_details() -> item.check_permission()
        # for the acting session user. Derive which existing baseline
        # role actually carries real Item read permission from live
        # metadata (never assume "Sales Manager" alone grants it).
        item_reader_roles = _derive_roles_with_required_permissions(
            "Item", REQUIRED_ITEM_PERMISSIONS
        )
        assert cls.salesperson_role in item_reader_roles, (
            "Live Item DocPerm metadata must grant '{0}' real read "
            "permission; derived qualifying roles were: {1}".format(
                cls.salesperson_role, sorted(item_reader_roles)
            )
        )
        cls.item_read_role = cls.salesperson_role

        cls.company = _get_or_create_company()
        _get_or_create_fiscal_year(cls.company)
        cls.item_code = _get_or_create_item()
        cls.customer = _get_or_create_discount_order_customer()

        # The owner actor holds BOTH the derived initiating role and the
        # derived approving role, to exercise the self-approval-denial
        # scenario. Its "Sales User" role already carries the Item-read
        # permission the real submit path needs.
        cls.owner_user = _get_or_create_user(
            OWNER_USER, roles=[cls.salesperson_role, cls.manager_role]
        )
        # A distinct, independent manager who only ever holds the derived
        # manager role (plus the existing baseline Item-read role the
        # real Approve submit path needs) and never creates/owns the
        # order under test.
        cls.independent_manager_user = _get_or_create_user(
            INDEPENDENT_MANAGER_USER, roles=[cls.manager_role, cls.item_read_role]
        )

        cls._created_orders = []
        frappe.set_user("Administrator")
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        import frappe

        frappe.set_user("Administrator")
        for so_name in cls._created_orders:
            if frappe.db.exists("Sales Order", so_name):
                so = frappe.get_doc("Sales Order", so_name)
                if so.docstatus == 1:
                    so.cancel()
                frappe.delete_doc(
                    "Sales Order", so_name, force=True, ignore_permissions=True
                )
        frappe.db.commit()

    def setUp(self):
        self.addCleanup(self._restore_administrator)

    def _restore_administrator(self):
        import frappe

        frappe.set_user("Administrator")

    def _track(self, so_name):
        type(self)._created_orders.append(so_name)

    def test_low_discount_salesperson_self_submits_without_manager(self):
        """additional_discount_percentage <= 10 -> the owning salesperson
        (real "Sales User" session) can Submit directly into Approved
        (docstatus 1); no manager approval is required."""
        import frappe
        from frappe.model.workflow import apply_workflow

        so = _build_sales_order(
            self.customer, self.company, self.item_code,
            discount_percentage=5, as_user=self.owner_user,
        )
        self._track(so.name)
        frappe.db.commit()

        self.assertEqual(so.additional_discount_percentage, 5)
        self.assertEqual(so.workflow_state, "Draft")
        self.assertEqual(so.docstatus, 0)

        frappe.set_user(self.owner_user)
        self.assertEqual(frappe.session.user, self.owner_user)
        self.assertIn(self.salesperson_role, frappe.get_roles(self.owner_user))
        self.assertTrue(
            frappe.has_permission("Sales Order", "submit", doc=so, user=self.owner_user),
            "Sales User must hold live submit permission on Sales Order "
            "(installed by after_migrate) before a low-discount self-submit.",
        )
        self.assertTrue(
            frappe.has_permission("Item", "read", user=self.owner_user),
            "Sales User must hold live read permission on Item before a "
            "real Sales Order submit can run get_item_details().",
        )

        apply_workflow(so, "Submit")
        frappe.db.commit()

        so.reload()
        self.assertEqual(so.docstatus, 1)
        self.assertEqual(so.workflow_state, "Approved")

    def test_high_discount_requires_independent_manager_approval(self):
        """additional_discount_percentage > 10 -> the owning salesperson
        can only Send for Approval (stays docstatus 0, Pending Manager
        Approval). The same owner, even though they also hold the
        manager-level role, is denied by apply_workflow()'s real
        self-approval rule when they try to Approve their own order
        (allow_self_approval = 0 on that transition); the order remains
        Pending / docstatus 0. Only a different, independent manager can
        complete the Approve transition into Approved (docstatus 1)."""
        import frappe
        from frappe.model.workflow import apply_workflow

        so = _build_sales_order(
            self.customer, self.company, self.item_code,
            discount_percentage=20, as_user=self.owner_user,
        )
        self._track(so.name)
        frappe.db.commit()

        self.assertEqual(so.additional_discount_percentage, 20)
        self.assertEqual(so.workflow_state, "Draft")
        self.assertEqual(so.docstatus, 0)
        self.assertEqual(so.owner, self.owner_user)

        # Salesperson sends the big-discount order for manager approval.
        frappe.set_user(self.owner_user)
        self.assertEqual(frappe.session.user, self.owner_user)
        self.assertTrue(
            frappe.has_permission("Sales Order", "write", doc=so, user=self.owner_user),
            "Sales User must hold live write permission on Sales Order "
            "before Send for Approval.",
        )
        apply_workflow(so, "Send for Approval")
        frappe.db.commit()

        so.reload()
        self.assertEqual(so.docstatus, 0)
        self.assertEqual(so.workflow_state, "Pending Manager Approval")

        # The owner also holds the manager-level role (the approving
        # role) -- but is still the document owner/requester, so the
        # real ERPNext/Frappe self-approval denial (allow_self_approval =
        # 0 on this transition) must block them. apply_workflow() raises
        # this frappe.throw()-based ValidationError BEFORE ever calling
        # doc.submit(), so this denial path never even reaches the
        # nested Item-read permission check below.
        frappe.set_user(self.owner_user)
        self.assertEqual(frappe.session.user, self.owner_user)
        self.assertIn(self.manager_role, frappe.get_roles(self.owner_user))
        self.assertEqual(so.owner, self.owner_user)

        with self.assertRaises(frappe.ValidationError):
            apply_workflow(so, "Approve")
        frappe.db.rollback()

        so.reload()
        self.assertEqual(so.docstatus, 0)
        self.assertEqual(so.workflow_state, "Pending Manager Approval")

        # A different, independent manager (who does not own this order)
        # can complete the approval. This performs a real doc.submit(),
        # which independently runs get_item_details() -> Item read
        # permission check for this acting session user -- so assert
        # that live grant immediately before the call too.
        frappe.set_user(self.independent_manager_user)
        self.assertEqual(frappe.session.user, self.independent_manager_user)
        self.assertIn(self.manager_role, frappe.get_roles(self.independent_manager_user))
        self.assertIn(self.item_read_role, frappe.get_roles(self.independent_manager_user))
        self.assertNotEqual(so.owner, self.independent_manager_user)
        self.assertTrue(
            frappe.has_permission(
                "Sales Order", "submit", doc=so, user=self.independent_manager_user
            ),
            "Sales Manager must hold live submit permission on Sales Order "
            "(installed by after_migrate) before completing a manager approval.",
        )
        self.assertTrue(
            frappe.has_permission(
                "Item", "read", user=self.independent_manager_user
            ),
            "The independent manager must hold live Item read permission "
            "(via the existing baseline 'Sales User' role) before the "
            "Approve transition's real doc.submit() can run "
            "get_item_details() for this acting session user.",
        )

        apply_workflow(so, "Approve")
        frappe.db.commit()

        so.reload()
        self.assertEqual(so.docstatus, 1)
        self.assertEqual(so.workflow_state, "Approved")


if __name__ == "__main__":
    unittest.main()
