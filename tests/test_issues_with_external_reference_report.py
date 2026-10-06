"""Focused, dependency-free tests for the "Issues with External Reference"
Query Report.

These tests are intentionally Frappe-free (v16-compatible structural checks
only) since Frappe is not available in this environment. They validate:

  * The Report JSON definition exists, is valid JSON, and has the canonical
    fields required for a standard Query Report (name, report_type,
    ref_doctype, module).
  * Exactly one adjacent .sql file exists next to the JSON definition and
    contains the requested SELECT fields, including the portable/explicit
    `name AS issue` expression.
  * The SQL is read-only (no mutating statements).
  * The Issue custom field fixture backing `synthetic_reference` is present.
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = (
    REPO_ROOT
    / "synthetic_build_target_app"
    / "synthetic_build_target_app"
    / "report"
    / "issues_with_external_reference"
)
REPORT_JSON = REPORT_DIR / "issues_with_external_reference.json"

REQUIRED_FIELDS = [
    "name AS issue",
    "subject",
    "status",
    "synthetic_reference",
    "owner",
    "modified",
]


class TestIssuesWithExternalReferenceReport(unittest.TestCase):
    def test_report_directory_exists(self):
        self.assertTrue(REPORT_DIR.is_dir(), f"Missing report directory: {REPORT_DIR}")

    def test_report_json_is_valid_and_canonical(self):
        self.assertTrue(REPORT_JSON.is_file(), f"Missing report JSON: {REPORT_JSON}")
        data = json.loads(REPORT_JSON.read_text(encoding="utf-8"))

        self.assertEqual(data.get("doctype"), "Report")
        self.assertEqual(data.get("name"), "Issues with External Reference")
        self.assertEqual(data.get("report_name"), "Issues with External Reference")
        self.assertEqual(data.get("report_type"), "Query Report")
        self.assertEqual(data.get("ref_doctype"), "Issue")
        self.assertEqual(data.get("module"), "Synthetic Build Target App")
        self.assertEqual(data.get("is_standard"), "Yes")

    def test_exactly_one_adjacent_sql_file(self):
        sql_files = sorted(REPORT_DIR.glob("*.sql"))
        self.assertEqual(
            len(sql_files),
            1,
            f"Expected exactly one .sql file adjacent to report JSON, found: {sql_files}",
        )

    def test_sql_contains_requested_fields(self):
        sql_files = list(REPORT_DIR.glob("*.sql"))
        self.assertEqual(len(sql_files), 1)
        sql_text = sql_files[0].read_text(encoding="utf-8")

        for field_expr in REQUIRED_FIELDS:
            self.assertIn(
                field_expr,
                sql_text,
                f"Expected field expression {field_expr!r} in SQL report definition",
            )

        # Issue identifier must be portable/explicit and unqualified.
        self.assertRegex(sql_text, r"(?<!\.)\bname AS issue\b")
        self.assertIn("tabIssue", sql_text)

    def test_sql_is_read_only(self):
        sql_files = list(REPORT_DIR.glob("*.sql"))
        self.assertEqual(len(sql_files), 1)
        sql_text = sql_files[0].read_text(encoding="utf-8")
        upper = sql_text.upper()

        self.assertTrue(upper.strip().startswith("SELECT"))
        for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE "):
            self.assertNotIn(forbidden, upper, f"SQL must be read-only, found: {forbidden!r}")

    def test_no_json_embedded_or_python_only_sql(self):
        data = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        # A standard Query Report must not embed the SQL query directly in
        # the JSON definition; the query must live in the adjacent .sql file.
        self.assertNotIn("query", data)

        py_files = list(REPORT_DIR.glob("*.py"))
        for py_file in py_files:
            text = py_file.read_text(encoding="utf-8")
            self.assertNotRegex(
                text,
                r"(?i)select\s+.*from\s+`?tabissue`?",
                "SQL must not be defined solely in Python for this report",
            )

    def test_issue_custom_field_fixture_present(self):
        fixture_path = (
            REPO_ROOT / "synthetic_build_target_app" / "fixtures" / "custom_field.json"
        )
        self.assertTrue(fixture_path.is_file())
        fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
        matches = [
            f
            for f in fixtures
            if f.get("doctype") == "Custom Field"
            and f.get("dt") == "Issue"
            and f.get("fieldname") == "synthetic_reference"
        ]
        self.assertEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main()
