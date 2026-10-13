app_name = "synthetic_build_target_app"
app_title = "Synthetic Build Target App"
app_publisher = "Easytouch Test"
app_description = "Fabricated disposable Frappe app used only as a D1 GitHub integration target"
app_email = "fixture@example.test"
app_license = "MIT"

fixtures = ["Custom Field"]

# Every time a submitted Sales Invoice is created, automatically create a
# Project for that invoice using the customer name and invoice number. The
# handler is idempotent: it checks for the deterministic Project name
# before inserting, so retried on_submit events never create duplicates.
#
# Low-stock alerting: every real source transaction whose lifecycle changes
# Bin quantities is hooked on both submit and cancel, because either
# direction can cross the "important item below threshold" line. Sales
# Invoice and Purchase Invoice only actually move stock (and are therefore
# only checked) when their ``update_stock`` flag is enabled; the handler
# itself re-verifies that flag before queuing anything.
doc_events = {
    "Sales Invoice": {
        "on_submit": [
            "synthetic_build_target_app.sales_invoice_automation.create_project_on_submit",
            "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
        ],
        "on_cancel": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
    },
    "Purchase Invoice": {
        "on_submit": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
    },
    "Delivery Note": {
        "on_submit": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
    },
    "Purchase Receipt": {
        "on_submit": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
    },
    "Stock Entry": {
        "on_submit": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
    },
    "Stock Reconciliation": {
        "on_submit": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.low_stock_alert_automation.queue_low_stock_check",
    },
}
