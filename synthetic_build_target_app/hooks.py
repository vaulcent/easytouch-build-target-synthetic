app_name = "synthetic_build_target_app"
app_title = "Synthetic Build Target App"
app_publisher = "Easytouch Test"
app_description = "Fabricated disposable Frappe app used only as a D1 GitHub integration target"
app_email = "fixture@example.test"
app_license = "MIT"

after_migrate = (
    "synthetic_build_target_app.synthetic_build_target_app.install."
    "ensure_important_item_notification"
)

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
# "Stock Ledger Entry" -- "on_submit" is the general, stock-ledger-
# compatible hook that makes the existing "Important Item Low Stock Alert"
# Notification actually fire after real ERPNext stock movements (Stock
# Entry, Delivery Note, Purchase Receipt, Sales Invoice with
# update_stock, etc.). ERPNext updates Bin quantities via direct database
# writes rather than Bin.save(), so the Notification DocType's built-in
# "Value Change" detection never observes a change on its own; this hook
# reads the final, post-commit warehouse Bin quantity instead.
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
    },
    "Stock Ledger Entry": {
        "on_submit": (
            "synthetic_build_target_app.synthetic_build_target_app."
            "stock_ledger_alerts.queue_important_item_low_stock_alert"
        ),
    },
}
