"""Authoritative ERPNext-backed evidence for the low-stock alert automation.

Requirement: when stock for an item marked "important" falls below 10,
the Purchase Manager must automatically receive an alert.

This module is loaded by ``bench execute`` against a disposable
ERPNext v16 site with an active Frappe database context. It performs
real Stock Entry submissions/cancellations (the actual lifecycle events
that change Bin.actual_qty) and asserts the resulting Notification Log
rows, rather than inspecting source text or mocking Frappe/the database.

In the local, Frappe-less coding sandbox these cases are skipped via
``skipUnless``; after ``finish`` they must execute for real inside the
installed ERPNext validation site.
"""

import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ('automation',)

try:
    import frappe

    FRAPPE_AVAILABLE = True
except ImportError:
    FRAPPE_AVAILABLE = False


RECIPIENT_EMAIL = "low.stock.alert.recipient@example.test"
IMPORTANT_ITEM_CODE = "LOW-STOCK-ALERT-IMPORTANT-ITEM"
UNMARKED_ITEM_CODE = "LOW-STOCK-ALERT-UNMARKED-ITEM"


def _ensure_frappe_context():
    """Reuse the active bench execute DB context when present; only
    initialise/connect from frappe.local.site when genuinely needed."""
    if getattr(frappe.local, "db", None):
        return
    frappe.init(site=frappe.local.site)
    frappe.connect()


def _get_or_create_warehouse_type_transit():
    if not frappe.db.exists("Warehouse Type", "Transit"):
        frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(
            ignore_permissions=True
        )


def _get_or_create_company():
    existing = frappe.get_all("Company", limit=1, pluck="name")
    if existing:
        return existing[0]
    _get_or_create_warehouse_type_transit()
    company = frappe.get_doc(
        {
            "doctype": "Company",
            "company_name": "Low Stock Alert Test Co",
            "abbr": "LSATC",
            "default_currency": "USD",
            "country": "United States",
        }
    ).insert(ignore_permissions=True)
    return company.name


def _get_or_create_item_group():
    leaf = frappe.get_all("Item Group", filters={"is_group": 0}, limit=1, pluck="name")
    if leaf:
        return leaf[0]
    roots = frappe.get_all(
        "Item Group", filters={"is_group": 1}, order_by="lft asc", limit=1, pluck="name"
    )
    if roots:
        root = roots[0]
    else:
        root = frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": "Low Stock Alert Test Root",
                "is_group": 1,
            }
        ).insert(ignore_permissions=True).name
    leaf_doc = frappe.get_doc(
        {
            "doctype": "Item Group",
            "item_group_name": "Low Stock Alert Test Leaf",
            "is_group": 0,
            "parent_item_group": root,
        }
    ).insert(ignore_permissions=True)
    return leaf_doc.name


def _get_or_create_uom():
    if frappe.db.exists("UOM", "Nos"):
        return "Nos"
    return frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(
        ignore_permissions=True
    ).name


def _get_or_create_warehouse(company):
    existing = frappe.get_all(
        "Warehouse", filters={"company": company, "is_group": 0}, limit=1, pluck="name"
    )
    if existing:
        return existing[0]
    return frappe.get_doc(
        {
            "doctype": "Warehouse",
            "warehouse_name": "Low Stock Alert Test Store",
            "company": company,
        }
    ).insert(ignore_permissions=True).name


def _ensure_fiscal_year_covers_today(company):
    from frappe.utils import getdate, nowdate

    today = getdate(nowdate())
    fy_name = str(today.year)
    if frappe.db.exists("Fiscal Year", fy_name):
        fy = frappe.get_doc("Fiscal Year", fy_name)
        company_rows = [row.company for row in fy.get("companies") or []]
        if company_rows and company not in company_rows:
            fy.append("companies", {"company": company})
            fy.save(ignore_permissions=True)
        return fy.name
    fy = frappe.get_doc(
        {
            "doctype": "Fiscal Year",
            "year": fy_name,
            "year_start_date": today.replace(month=1, day=1),
            "year_end_date": today.replace(month=12, day=31),
        }
    ).insert(ignore_permissions=True)
    return fy.name


def _ensure_stock_entry_type(name, purpose):
    if not frappe.db.exists("Stock Entry Type", name):
        frappe.get_doc(
            {"doctype": "Stock Entry Type", "name": name, "purpose": purpose}
        ).insert(ignore_permissions=True)
    return name


def _ensure_recipient_user(email):
    if not frappe.db.exists("User", email):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Low Stock Alert Recipient",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        ).insert(ignore_permissions=True)
    else:
        user = frappe.get_doc("User", email)
        if not user.enabled:
            user.enabled = 1
            user.save(ignore_permissions=True)
    if not frappe.db.exists(
        "Has Role", {"parent": email, "role": "Purchase Manager", "parenttype": "User"}
    ):
        user.add_roles("Purchase Manager")
    return email


def _create_item(item_code, important, item_group, uom):
    if frappe.db.exists("Item", item_code):
        return item_code
    frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": item_code,
            "item_name": item_code,
            "item_group": item_group,
            "stock_uom": uom,
            "is_stock_item": 1,
            "important_item": 1 if important else 0,
        }
    ).insert(ignore_permissions=True)
    return item_code


def _make_stock_entry(company, stock_entry_type, purpose, item_code, uom, qty, *,
                       s_warehouse=None, t_warehouse=None, basic_rate=None):
    """Build, name uniquely, and insert a Stock Entry. Returns the
    already-inserted document; callers must NOT call .insert() again on
    the returned document (doing so would attempt a second INSERT with
    the same already-assigned name and raise DuplicateEntryError)."""
    from frappe.utils import nowdate

    se = frappe.new_doc("Stock Entry")
    se.company = company
    se.stock_entry_type = stock_entry_type
    se.purpose = purpose
    se.posting_date = nowdate()
    row = {"item_code": item_code, "qty": qty, "uom": uom, "stock_uom": uom, "conversion_factor": 1}
    if s_warehouse:
        row["s_warehouse"] = s_warehouse
    if t_warehouse:
        row["t_warehouse"] = t_warehouse
    if basic_rate is not None:
        row["basic_rate"] = basic_rate
    se.append("items", row)
    # Explicitly assign a globally-unique name instead of relying solely
    # on the shared "MAT-STE-.YYYY.-" naming series counter. Frappe only
    # autonames a document when `doc.name` is still falsy at insert time,
    # so pre-setting a collision-proof name here removes any dependency
    # on naming-series state left behind by earlier runs/other behavior
    # test modules against the same cumulative disposable site.
    se.flags.name_set = True
    se.name = "LSA-STE-{0}-{1}".format(
        purpose.replace(" ", "")[:3].upper(), frappe.generate_hash(length=12)
    )
    se.insert(ignore_permissions=True)
    return se


def _submit_with_synchronous_notifications(doc):
    """Submit the real transaction and commit while frappe.in_test is
    True, so Frappe's after-commit enqueue (enqueue_after_commit) runs
    synchronously during this very commit, and the nested Notification
    Log enqueue inside it also runs synchronously via Frappe's own
    test path instead of going to a background queue worker (the
    disposable bench-execute validation lane does not run queue
    workers). The prior values are restored only after the commit.

    Both ``frappe.in_test`` and ``frappe.flags.in_test`` are set: the
    latter is the attribute actually consulted by
    ``frappe.utils.background_jobs.enqueue`` (to decide whether to run
    ``now`` instead of queuing to Redis) and forwarded as
    ``now=frappe.flags.in_test`` by
    ``notification_log.enqueue_create_notification``, so both must be
    True for the whole submit+commit window for delivery to be
    synchronous and queue-worker-free.
    """
    prior_in_test = frappe.in_test
    prior_flags_in_test = frappe.flags.in_test
    frappe.in_test = True
    frappe.flags.in_test = True
    try:
        doc.submit()
        frappe.db.commit()
    finally:
        frappe.in_test = prior_in_test
        frappe.flags.in_test = prior_flags_in_test


def _cancel_with_synchronous_notifications(doc):
    prior_in_test = frappe.in_test
    prior_flags_in_test = frappe.flags.in_test
    frappe.in_test = True
    frappe.flags.in_test = True
    try:
        doc.reload()
        doc.cancel()
        frappe.db.commit()
    finally:
        frappe.in_test = prior_in_test
        frappe.flags.in_test = prior_flags_in_test


def _total_actual_qty(item_code):
    row = frappe.db.sql(
        "select sum(actual_qty) from `tabBin` where item_code=%s", item_code
    )
    return row[0][0] or 0


@unittest.skipUnless(FRAPPE_AVAILABLE, "Frappe is not available in the local sandbox")
class LowStockAlertERPBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_frappe_context()
        frappe.set_user("Administrator")

        cls.company = _get_or_create_company()
        cls.item_group = _get_or_create_item_group()
        cls.uom = _get_or_create_uom()
        cls.warehouse = _get_or_create_warehouse(cls.company)
        _ensure_fiscal_year_covers_today(cls.company)
        cls.receipt_type = _ensure_stock_entry_type("Material Receipt", "Material Receipt")
        cls.issue_type = _ensure_stock_entry_type("Material Issue", "Material Issue")
        cls.recipient = _ensure_recipient_user(RECIPIENT_EMAIL)

        cls._created_stock_entries = []

    @classmethod
    def tearDownClass(cls):
        for se_name in reversed(cls._created_stock_entries):
            try:
                se = frappe.get_doc("Stock Entry", se_name)
                se.reload()
                if se.docstatus == 1:
                    se.cancel()
                    frappe.db.commit()
            except Exception:
                frappe.db.rollback()
        for item_code in (IMPORTANT_ITEM_CODE, UNMARKED_ITEM_CODE):
            frappe.db.delete(
                "Notification Log", {"document_type": "Item", "document_name": item_code}
            )
        frappe.db.commit()

    def _receipt_then_issue(self, item_code, important):
        _create_item(item_code, important, self.item_group, self.uom)
        frappe.db.delete(
            "Notification Log", {"document_type": "Item", "document_name": item_code}
        )
        frappe.db.commit()

        receipt = _make_stock_entry(
            self.company,
            self.receipt_type,
            "Material Receipt",
            item_code,
            self.uom,
            15,
            t_warehouse=self.warehouse,
            basic_rate=10,
        )
        receipt.submit()
        frappe.db.commit()
        self.__class__._created_stock_entries.append(receipt.name)

        self.assertEqual(_total_actual_qty(item_code), 15)

        # _make_stock_entry already inserts the document; do not call
        # .insert() again here, that would attempt a second INSERT with
        # the same already-assigned primary key and raise
        # DuplicateEntryError.
        issue = _make_stock_entry(
            self.company,
            self.issue_type,
            "Material Issue",
            item_code,
            self.uom,
            10,
            s_warehouse=self.warehouse,
        )
        _submit_with_synchronous_notifications(issue)
        self.__class__._created_stock_entries.append(issue.name)

        self.assertEqual(_total_actual_qty(item_code), 5)
        return receipt, issue

    def test_marked_important_item_below_threshold_alerts_purchase_manager(self):
        receipt, issue = self._receipt_then_issue(IMPORTANT_ITEM_CODE, important=True)

        logs = frappe.get_all(
            "Notification Log",
            filters={"document_type": "Item", "document_name": IMPORTANT_ITEM_CODE},
            fields=["for_user"],
        )
        self.assertTrue(
            logs, "Expected a Notification Log for the low-stock important item"
        )
        self.assertIn(
            RECIPIENT_EMAIL,
            [log.for_user for log in logs],
            "Expected the enabled Purchase Manager recipient to be alerted",
        )

        # Cancellation must recalculate the reversed quantity back above
        # the threshold.
        _cancel_with_synchronous_notifications(issue)
        self.assertEqual(_total_actual_qty(IMPORTANT_ITEM_CODE), 15)

    def test_unmarked_item_below_threshold_does_not_alert(self):
        self._receipt_then_issue(UNMARKED_ITEM_CODE, important=False)

        logs = frappe.get_all(
            "Notification Log",
            filters={"document_type": "Item", "document_name": UNMARKED_ITEM_CODE},
        )
        self.assertFalse(
            logs, "An item not marked important must never trigger a low-stock alert"
        )


if __name__ == "__main__":
    unittest.main()
