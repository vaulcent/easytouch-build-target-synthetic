"""Evidence for the "Salesperson Sales Summary" custom Query Report.

The report shows, for each Salesperson within a selected posting_date
range: total sales, collected amount, outstanding amount, gross profit,
and the number of distinct customers sold to. It is implemented as a
standard Frappe Query Report (Report JSON + an adjacent, read-only .sql
file) under
``synthetic_build_target_app/report/salesperson_sales_summary/``.

``TestSalespersonSalesSummaryReportArtifact`` is a no-Frappe structural
check of that artifact shape. ``TestSalespersonSalesSummaryReportFrappeBacked``
is the authoritative behavioral evidence: it seeds real ERPNext v16
masters/documents, submits a real Sales Invoice with a real Sales Team
allocation, and executes the actual .sql file via ``frappe.db.sql`` to
assert the returned, aggregated metrics -- not source text.
"""

import importlib.util
import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("report",)

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(
    APP_ROOT,
    "synthetic_build_target_app",
    "synthetic_build_target_app",
    "report",
    "salesperson_sales_summary",
)
JSON_PATH = os.path.join(REPORT_DIR, "salesperson_sales_summary.json")
SQL_PATH = os.path.join(REPORT_DIR, "salesperson_sales_summary.sql")

FRAPPE_AVAILABLE = importlib.util.find_spec("frappe") is not None


class TestSalespersonSalesSummaryReportArtifact(unittest.TestCase):
    """Structural checks for the report artifact (no Frappe required)."""

    @classmethod
    def setUpClass(cls):
        with open(JSON_PATH, "r", encoding="utf-8") as handle:
            cls.definition = json.load(handle)
        with open(SQL_PATH, "r", encoding="utf-8") as handle:
            cls.sql = handle.read()
        cls.sql_siblings = [
            name for name in os.listdir(REPORT_DIR) if name.endswith(".sql")
        ]

    def test_report_json_canonical_identity(self):
        self.assertEqual(self.definition["name"], "Salesperson Sales Summary")
        self.assertEqual(self.definition["report_type"], "Query Report")
        self.assertEqual(self.definition["ref_doctype"], "Sales Invoice")

    def test_exactly_one_adjacent_sql_file(self):
        self.assertEqual(len(self.sql_siblings), 1)
        self.assertEqual(self.sql_siblings[0], "salesperson_sales_summary.sql")

    def test_json_does_not_embed_the_query(self):
        self.assertNotIn("query", self.definition)

    def test_sql_contains_the_requested_select_fields(self):
        for expected in (
            "salesperson",
            "total_sales",
            "collected_amount",
            "outstanding_amount",
            "gross_profit",
            "number_of_customers",
        ):
            self.assertIn(expected, self.sql)

    def test_sql_is_a_select_only_read_only_statement(self):
        upper_sql = self.sql.upper()
        self.assertIn("SELECT", upper_sql)
        for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER "):
            self.assertNotIn(forbidden, upper_sql)

    def test_sql_uses_the_requested_date_range_filters(self):
        self.assertIn("%(from_date)s", self.sql)
        self.assertIn("%(to_date)s", self.sql)

    def test_issue_identifier_kept_portable_and_unqualified(self):
        self.assertIn("name AS issue", self.sql)


@unittest.skipUnless(
    FRAPPE_AVAILABLE,
    "Frappe is not installed in this local sandbox; behavioral evidence "
    "must come from a real ERPNext v16 site run.",
)
class TestSalespersonSalesSummaryReportFrappeBacked(unittest.TestCase):
    """Authoritative evidence on a real disposable ERPNext v16 site."""

    @classmethod
    def setUpClass(cls):
        import frappe
        from frappe.utils import add_days, nowdate

        cls.frappe = frappe

        if getattr(frappe.local, "db", None) is None:
            frappe.init(site=frappe.local.site)
            frappe.connect()

        cls.today = nowdate()
        cls.from_date = add_days(cls.today, -30)
        cls.to_date = add_days(cls.today, 1)

        cls.company = cls._ensure_company()
        cls.currency = (
            frappe.db.get_value("Company", cls.company, "default_currency")
            or "USD"
        )
        cls._ensure_fiscal_year(cls.company, cls.today)
        cls.customer_group = cls._ensure_leaf_group("Customer Group")
        cls.territory = cls._ensure_leaf_group("Territory")
        cls.customer = cls._ensure_customer(cls.customer_group, cls.territory)
        cls.item_code = cls._ensure_non_stock_item()
        cls.sales_person = cls._ensure_sales_person()
        cls.price_list = cls._ensure_selling_price_list()

        cls.invoice_name = cls._create_and_submit_invoice()
        frappe.db.commit()

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
                "company_name": "Easytouch Report Test Co",
                "abbr": "ERTC",
                "default_currency": "USD",
                "country": "United States",
            }
        )
        company.insert(ignore_permissions=True)
        return company.name

    @classmethod
    def _ensure_fiscal_year(cls, company, on_date):
        frappe = cls.frappe
        candidates = frappe.get_all(
            "Fiscal Year",
            filters={
                "year_start_date": ["<=", on_date],
                "year_end_date": [">=", on_date],
            },
            pluck="name",
        )
        for name in candidates:
            fy = frappe.get_doc("Fiscal Year", name)
            company_links = [row.company for row in (fy.get("companies") or [])]
            if not company_links or company in company_links:
                return fy.name

        year = frappe.utils.getdate(on_date).year
        fy = frappe.get_doc(
            {
                "doctype": "Fiscal Year",
                "year": "Easytouch Report Test FY %s" % year,
                "year_start_date": "%s-01-01" % year,
                "year_end_date": "%s-12-31" % year,
                "companies": [{"company": company}],
            }
        )
        fy.insert(ignore_permissions=True)
        return fy.name

    @classmethod
    def _ensure_leaf_group(cls, doctype):
        frappe = cls.frappe
        name_field = doctype.lower().replace(" ", "_") + "_name"
        parent_field = "parent_" + doctype.lower().replace(" ", "_")

        leaf = frappe.get_all(doctype, filters={"is_group": 0}, pluck="name", limit=1)
        if leaf:
            return leaf[0]

        roots = frappe.get_all(doctype, filters={"is_group": 1}, pluck="name", limit=1)
        if roots:
            root = roots[0]
        else:
            root_doc = frappe.get_doc(
                {
                    "doctype": doctype,
                    name_field: "Easytouch Report Test Root",
                    "is_group": 1,
                }
            )
            root_doc.insert(ignore_permissions=True)
            root = root_doc.name

        leaf_doc = frappe.get_doc(
            {
                "doctype": doctype,
                name_field: "Easytouch Report Test Leaf",
                "is_group": 0,
                parent_field: root,
            }
        )
        leaf_doc.insert(ignore_permissions=True)
        return leaf_doc.name

    @classmethod
    def _ensure_customer(cls, customer_group, territory):
        frappe = cls.frappe
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": "Easytouch Report Test Customer",
                "customer_group": customer_group,
                "territory": territory,
                "customer_type": "Individual",
            }
        )
        customer.insert(ignore_permissions=True)
        return customer.name

    @classmethod
    def _ensure_non_stock_item(cls):
        frappe = cls.frappe
        code = "EASYTOUCH-REPORT-TEST-ITEM"
        if frappe.db.exists("Item", code):
            return code

        leaf_groups = frappe.get_all(
            "Item Group", filters={"is_group": 0}, pluck="name", limit=1
        )
        if leaf_groups:
            group = leaf_groups[0]
        else:
            roots = frappe.get_all(
                "Item Group", filters={"is_group": 1}, pluck="name", limit=1
            )
            if roots:
                root = roots[0]
            else:
                root_doc = frappe.get_doc(
                    {
                        "doctype": "Item Group",
                        "item_group_name": "Easytouch Report Test Root",
                        "is_group": 1,
                    }
                )
                root_doc.insert(ignore_permissions=True)
                root = root_doc.name
            leaf_doc = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Easytouch Report Test Items",
                    "is_group": 0,
                    "parent_item_group": root,
                }
            )
            leaf_doc.insert(ignore_permissions=True)
            group = leaf_doc.name

        uoms = frappe.get_all("UOM", pluck="name", limit=1)
        if uoms:
            uom_name = uoms[0]
        else:
            uom_doc = frappe.get_doc(
                {"doctype": "UOM", "uom_name": "Easytouch Report Test Unit"}
            )
            uom_doc.insert(ignore_permissions=True)
            uom_name = uom_doc.name

        item = frappe.get_doc(
            {
                "doctype": "Item",
                "item_code": code,
                "item_name": code,
                "item_group": group,
                "stock_uom": uom_name,
                "is_stock_item": 0,
            }
        )
        item.insert(ignore_permissions=True)
        return item.name

    @classmethod
    def _ensure_sales_person(cls):
        frappe = cls.frappe
        name = "Easytouch Report Test Sales Person"
        if frappe.db.exists("Sales Person", name):
            return name
        doc = frappe.get_doc(
            {
                "doctype": "Sales Person",
                "sales_person_name": name,
                "is_group": 0,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name

    @classmethod
    def _ensure_selling_price_list(cls):
        frappe = cls.frappe
        existing = frappe.get_all(
            "Price List", filters={"selling": 1}, pluck="name", limit=1
        )
        if existing:
            return existing[0]
        price_list = frappe.get_doc(
            {
                "doctype": "Price List",
                "price_list_name": "Easytouch Report Test Selling",
                "selling": 1,
                "currency": cls.currency,
            }
        )
        price_list.insert(ignore_permissions=True)
        return price_list.name

    @classmethod
    def _create_and_submit_invoice(cls):
        frappe = cls.frappe
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": cls.customer,
                "company": cls.company,
                "posting_date": cls.today,
                "due_date": cls.today,
                "set_posting_time": 1,
                "currency": cls.currency,
                "conversion_rate": 1,
                "selling_price_list": cls.price_list,
                "price_list_currency": cls.currency,
                "plc_conversion_rate": 1,
                "items": [
                    {
                        "item_code": cls.item_code,
                        "qty": 1,
                        "rate": 1000,
                    }
                ],
                "sales_team": [
                    {
                        "sales_person": cls.sales_person,
                        "allocated_percentage": 100,
                    }
                ],
            }
        )
        invoice.insert(ignore_permissions=True)
        invoice.submit()
        return invoice.name

    def _run_report_sql(self, from_date, to_date):
        with open(SQL_PATH, "r", encoding="utf-8") as handle:
            sql = handle.read()
        return self.frappe.db.sql(
            sql,
            {"from_date": from_date, "to_date": to_date},
            as_dict=True,
        )

    def test_report_sql_aggregates_metrics_for_the_selected_date_range(self):
        rows = self._run_report_sql(self.from_date, self.to_date)
        matches = [r for r in rows if r.salesperson == self.sales_person]
        self.assertEqual(
            len(matches),
            1,
            "expected exactly one aggregated row for the seeded salesperson",
        )
        row = matches[0]
        self.assertAlmostEqual(float(row.total_sales), 1000.0, places=2)
        self.assertAlmostEqual(float(row.outstanding_amount), 1000.0, places=2)
        self.assertAlmostEqual(float(row.collected_amount), 0.0, places=2)
        self.assertAlmostEqual(float(row.gross_profit), 1000.0, places=2)
        self.assertEqual(int(row.number_of_customers), 1)
        self.assertEqual(row.issue, self.invoice_name)

    def test_report_sql_excludes_documents_outside_the_requested_range(self):
        outside_from = self.frappe.utils.add_days(self.to_date, 1)
        outside_to = self.frappe.utils.add_days(self.to_date, 2)
        rows = self._run_report_sql(outside_from, outside_to)
        matches = [r for r in rows if r.salesperson == self.sales_person]
        self.assertEqual(
            matches,
            [],
            "a date range after the invoice's posting_date must not "
            "return the seeded salesperson's row",
        )


if __name__ == "__main__":
    unittest.main()
