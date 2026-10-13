app_name = "synthetic_build_target_app"
app_title = "Synthetic Build Target App"
app_publisher = "Easytouch Test"
app_description = "Fabricated disposable Frappe app used only as a D1 GitHub integration target"
app_email = "fixture@example.test"
app_license = "MIT"

# Run all idempotent post-migrate integrations on every migrate: the
# Notification fixture backfill, keeping the real installed
# "Salesperson Sales Summary" Query Report's database "query" field in
# sync with the shipped, read-only salesperson_sales_summary.sql file (the
# on-disk Report JSON fixture deliberately does not embed the SQL itself),
# granting the "Sales Invoice Discount Approval" Workflow's two roles
# (Sales User, Sales Manager) the exact Sales Invoice read/write/create/
# submit permissions their workflow transitions require, and granting the
# "Sales Order Finance Approval" Workflow's two roles (Sales User, Finance
# Approval) the exact Sales Order read/write/create/submit permissions
# their workflow transitions require.
after_migrate = [
    "synthetic_build_target_app.synthetic_build_target_app.install.ensure_important_item_notification",
    "synthetic_build_target_app.synthetic_build_target_app.install.ensure_salesperson_sales_summary_report_query",
    "synthetic_build_target_app.synthetic_build_target_app.install.ensure_discount_approval_workflow_permissions",
    "synthetic_build_target_app.synthetic_build_target_app.install.ensure_sales_order_finance_approval_workflow_permissions",
]

# "Custom Field" fixtures are the app's custom field definitions (see
# fixtures/custom_field.json). The "Role" fixture entry below keeps its
# original filter (selecting "Sales Invoice Rate Override" for
# `bench export-fixtures`); Frappe's fixture *sync* (used on migrate/
# install) always imports every record present in the on-disk
# fixtures/role.json file regardless of this filter (the filter only
# controls what `export-fixtures` later re-selects from the live
# database), so fixtures/role.json's second record -- the "Finance
# Approval" role the "Sales Order Finance Approval" Workflow links to --
# is still provisioned idempotently on every site this app is installed/
# migrated onto. Both roles are assignable to users on a real site
# without any manual setup step.
#
# "Workflow State", "Workflow Action Master", and "Workflow" fixtures
# together provision two separate active Workflows (Frappe allows only
# one active Workflow per DocType, and these target two different
# DocTypes so both coexist safely):
#
# 1. "Sales Invoice Discount Approval" (document_type "Sales Invoice"): a
#    salesperson (Sales User role) can submit a Sales Invoice themselves
#    only when its additional_discount_percentage is 10% or less; above
#    10% the only allowed transition sends the invoice to "Pending
#    Manager Approval", which only the Sales Manager role may then
#    approve (submit).
#
# 2. "Sales Order Finance Approval" (document_type "Sales Order"): a
#    salesperson (Sales User role) can submit a Sales Order themselves
#    only when its grand_total is $5,000 or less; above $5,000 the only
#    allowed transition sends the order to "Pending Finance Approval",
#    which only the Finance Approval role may then approve (submit) into
#    the "Approved" state.
#
# Both are wired through standard Frappe Workflow states/transitions/
# conditions rather than a custom permission hook. See
# fixtures/workflow_state.json, fixtures/workflow_action_master.json, and
# fixtures/workflow.json for the full state/transition matrices (both
# json files now contain both workflows' states/actions -- again, every
# record in each file syncs on migrate regardless of the "filters" list
# below), and synthetic_build_target_app.synthetic_build_target_app.
# install.ensure_discount_approval_workflow_permissions /
# .ensure_sales_order_finance_approval_workflow_permissions for the
# idempotent Custom DocPerm grants that make each workflow's real submit
# steps possible for its roles.
fixtures = [
    "Custom Field",
    {
        "doctype": "Role",
        "filters": [["name", "=", "Sales Invoice Rate Override"]],
    },
    {
        "doctype": "Workflow State",
        "filters": [
            ["name", "in", ["Draft", "Pending Manager Approval", "Approved"]]
        ],
    },
    {
        "doctype": "Workflow Action Master",
        "filters": [
            ["name", "in", ["Submit", "Send for Approval", "Approve"]]
        ],
    },
    {
        "doctype": "Workflow",
        "filters": [["name", "=", "Sales Invoice Discount Approval"]],
    },
]

# Server-side validation lanes that prevent submitting a Sales Invoice when
# any item's selling rate is below its valuation rate, unless the acting
# user holds the "Sales Invoice Rate Override" role. Both the "validate"
# (save-time, early feedback) and "before_submit" (hard stop before
# submission) lanes call the same idempotent validation function so the
# rule cannot drift out of sync between the two lanes. That validation
# falls back to the real warehouse Bin valuation_rate (looked up by
# item_code + the row's own warehouse) whenever a row's own
# valuation_rate is empty, instead of skipping the check.
#
# Real validation proved that ERPNext's internally written Stock Ledger
# Entry rows are inserted via a direct db_insert as part of posting a
# stock transaction and never go through on_submit document-event
# dispatch themselves, so a "Stock Ledger Entry" -- "on_submit" hook is
# never actually called on a real site. The "Important Item Low Stock
# Alert" Notification is instead wired to "on_submit" of the real,
# originating submittable stock transactions -- Stock Entry, Delivery
# Note, Purchase Receipt, and Sales Invoice -- which are genuine Frappe
# document-lifecycle events that do fire. See
# synthetic_build_target_app.synthetic_build_target_app.stock_ledger_alerts
# for the after-commit Bin read and the important-item + low-stock gating.
#
# Sales Invoice's real "on_submit" event also fires
# sales_invoice_project.create_project_for_submitted_sales_invoice, which
# automatically creates a Project named from the customer name and
# invoice number for every submitted Sales Invoice, idempotently linked
# back to that invoice via the "sales_invoice" Custom Field on Project
# (see fixtures/custom_field.json and
# synthetic_build_target_app.synthetic_build_target_app.sales_invoice_project).
# Both handlers are real Frappe on_submit hooks for the same DocType and
# event, wired as a *list* (not a tuple) so Frappe's hook-merging utility
# flattens/extends the two dotted method paths into separate entries
# (frappe.get_hooks only extends plain Python lists; a tuple is instead
# appended as a single nested object, which breaks the hook dispatcher's
# ``method_string.split(".")`` call at submit time) -- both handlers run
# on every real submission.
doc_events = {
    "Sales Invoice": {
        "validate": (
            "synthetic_build_target_app.synthetic_build_target_app."
            "sales_invoice_validations.validate_selling_rate_against_valuation_rate"
        ),
        "before_submit": (
            "synthetic_build_target_app.synthetic_build_target_app."
            "sales_invoice_validations.validate_selling_rate_against_valuation_rate"
        ),
        "on_submit": [
            "synthetic_build_target_app.synthetic_build_target_app."
            "stock_ledger_alerts.queue_important_item_low_stock_alert",
            "synthetic_build_target_app.synthetic_build_target_app."
            "sales_invoice_project.create_project_for_submitted_sales_invoice",
        ],
    },
    "Stock Entry": {
        "on_submit": (
            "synthetic_build_target_app.synthetic_build_target_app."
            "stock_ledger_alerts.queue_important_item_low_stock_alert"
        ),
    },
    "Delivery Note": {
        "on_submit": (
            "synthetic_build_target_app.synthetic_build_target_app."
            "stock_ledger_alerts.queue_important_item_low_stock_alert"
        ),
    },
    "Purchase Receipt": {
        "on_submit": (
            "synthetic_build_target_app.synthetic_build_target_app."
            "stock_ledger_alerts.queue_important_item_low_stock_alert"
        ),
    },
}
