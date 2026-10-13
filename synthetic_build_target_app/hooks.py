app_name = "synthetic_build_target_app"
app_title = "Synthetic Build Target App"
app_publisher = "Easytouch Test"
app_description = "Fabricated disposable Frappe app used only as a D1 GitHub integration target"
app_email = "fixture@example.test"
app_license = "MIT"

# Run both idempotent post-migrate integrations on every migrate: the
# Notification fixture backfill, and keeping the real installed
# "Salesperson Sales Summary" Query Report's database "query" field in
# sync with the shipped, read-only salesperson_sales_summary.sql file (the
# on-disk Report JSON fixture deliberately does not embed the SQL itself).
after_migrate = [
    "synthetic_build_target_app.synthetic_build_target_app.install.ensure_important_item_notification",
    "synthetic_build_target_app.synthetic_build_target_app.install.ensure_salesperson_sales_summary_report_query",
]

# "Custom Field" fixtures are the app's custom field definitions (see
# fixtures/custom_field.json). The "Role" fixture provisions the
# "Sales Invoice Rate Override" role idempotently on every site this app is
# installed/migrated onto (see fixtures/role.json), so the role is
# assignable to users on a real site without any manual setup step.
fixtures = [
    "Custom Field",
    {
        "doctype": "Role",
        "filters": [["name", "=", "Sales Invoice Rate Override"]],
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
