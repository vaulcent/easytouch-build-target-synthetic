"""Authoritative ERPNext-backed behavior test for the Lead "Expected Deal
Value" custom field.

This module proves, against a real (disposable) ERPNext v16 site with Frappe
installed, that after importing the app's Custom Field fixtures:

  - A Custom Field named "Lead-expected_deal_value" exists.
  - It targets DocType "Lead".
  - Its label is "Expected Deal Value".
  - Its fieldtype is "Currency".
  - It is positioned directly after the "annual_revenue" field
    (insert_after == "annual_revenue").

No SQLite or mocked Frappe/database access is used as evidence: if the real
`frappe` package is not importable in the local sandbox, the authoritative
case is skipped rather than faked. When Frappe *is* available (i.e. inside
the disposable ERPNext v16 validation lane), this module actively attempts
several real site-discovery strategies -- including a site already bound to
the current test runner/process -- before concluding no site is reachable,
so the authoritative evidence is never silently skipped on a real site.
"""

import json
import os
import unittest

EASYTOUCH_ERP_BEHAVIOR_KINDS = ("custom_field",)

try:
    import frappe  # type: ignore
    FRAPPE_AVAILABLE = True
except Exception:
    FRAPPE_AVAILABLE = False

_RESOLVED_SITE = {"name": None, "owns_connection": False}


def _site_already_bound():
    """True if the current process already has an initialized Frappe site
    (e.g. the test was launched via `bench run-tests`, which performs its
    own frappe.init()/frappe.connect() before handing control to unittest).
    """
    if not FRAPPE_AVAILABLE:
        return False
    try:
        site = getattr(frappe.local, "site", None)
        if site and getattr(frappe.local, "db", None):
            return True
    except Exception:
        pass
    return False


def _discover_site_candidates():
    candidates = []
    for env_var in ("FRAPPE_SITE", "SITE_NAME", "SITE"):
        value = os.environ.get(env_var)
        if value:
            candidates.append(value)

    for sites_root in (
        os.environ.get("SITES_PATH"),
        "sites",
        os.path.join(os.getcwd(), "sites"),
        "/home/frappe/frappe-bench/sites",
    ):
        if not sites_root or not os.path.isdir(sites_root):
            continue
        try:
            found = [
                d
                for d in sorted(os.listdir(sites_root))
                if os.path.isfile(os.path.join(sites_root, d, "site_config.json"))
            ]
        except Exception:
            found = []
        for site in found:
            if site not in candidates:
                candidates.append(site)
        if found:
            break
    return candidates


def _frappe_site_configured():
    """Best-effort check that a real Frappe site context can be reached.

    We deliberately avoid any sqlite or mock shortcuts. This returns True
    when either (a) the surrounding test runner already bound a real
    connected site to this process, or (b) a genuine Frappe site can be
    located (via env vars or a bench `sites/` directory scan) and
    connected to. Otherwise it returns False and the authoritative case
    skips, which is only expected when Frappe itself is unavailable in this
    local sandbox.
    """
    if not FRAPPE_AVAILABLE:
        return False

    if _site_already_bound():
        _RESOLVED_SITE["name"] = frappe.local.site
        _RESOLVED_SITE["owns_connection"] = False
        return True

    for candidate in _discover_site_candidates():
        try:
            frappe.init(site=candidate)
            frappe.connect()
            _RESOLVED_SITE["name"] = candidate
            _RESOLVED_SITE["owns_connection"] = True
            return True
        except Exception:
            try:
                frappe.destroy()
            except Exception:
                pass
            continue
    return False


@unittest.skipUnless(
    _frappe_site_configured(),
    "Requires a real, connectable ERPNext v16 Frappe site; Frappe itself "
    "(or any reachable site) is unavailable in this local sandbox.",
)
class TestLeadExpectedDealValueCustomField(unittest.TestCase):
    """Authoritative ERP behavior: Lead gets an "Expected Deal Value" field."""

    @classmethod
    def setUpClass(cls):
        # Import the app's Custom Field fixture into the connected site so
        # the test proves post-import reality, not source-file shape alone.
        fixture_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "synthetic_build_target_app",
            "fixtures",
            "custom_field.json",
        )

        with open(fixture_path, "r", encoding="utf-8") as fh:
            records = json.load(fh)

        for record in records:
            if record.get("dt") != "Lead":
                continue
            if frappe.db.exists("Custom Field", record["name"]):
                doc = frappe.get_doc("Custom Field", record["name"])
                for key in ("dt", "fieldname", "fieldtype", "label", "insert_after"):
                    if key in record:
                        setattr(doc, key, record[key])
                doc.save(ignore_permissions=True)
            else:
                doc = frappe.get_doc(record)
                doc.insert(ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache(doctype="Lead")

    @classmethod
    def tearDownClass(cls):
        if FRAPPE_AVAILABLE and _RESOLVED_SITE.get("owns_connection"):
            try:
                frappe.destroy()
            except Exception:
                pass

    def test_custom_field_exists_with_exact_metadata(self):
        self.assertTrue(
            frappe.db.exists("Custom Field", "Lead-expected_deal_value"),
            "Expected Custom Field 'Lead-expected_deal_value' to exist after fixture import",
        )

        cf = frappe.get_doc("Custom Field", "Lead-expected_deal_value")
        self.assertEqual(cf.dt, "Lead")
        self.assertEqual(cf.label, "Expected Deal Value")
        self.assertEqual(cf.fieldtype, "Currency")
        self.assertEqual(cf.insert_after, "annual_revenue")

    def test_field_appears_in_lead_meta_after_annual_revenue(self):
        meta = frappe.get_meta("Lead")
        fieldnames = [df.fieldname for df in meta.fields]

        self.assertIn("expected_deal_value", fieldnames)
        self.assertIn("annual_revenue", fieldnames)

        annual_revenue_idx = fieldnames.index("annual_revenue")
        expected_deal_value_idx = fieldnames.index("expected_deal_value")
        self.assertEqual(
            expected_deal_value_idx,
            annual_revenue_idx + 1,
            "Expected Deal Value should be placed directly below Annual Revenue",
        )

        field = meta.get_field("expected_deal_value")
        self.assertEqual(field.fieldtype, "Currency")
        self.assertEqual(field.label, "Expected Deal Value")


if __name__ == "__main__":
    unittest.main()
