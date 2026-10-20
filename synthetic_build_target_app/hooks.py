app_name = "synthetic_build_target_app"
app_title = "Synthetic Build Target App"
app_publisher = "Easytouch Test"
app_description = "Fabricated disposable Frappe app used only as a D1 GitHub integration target"
app_email = "fixture@example.test"
app_license = "MIT"

fixtures = ["Custom Field"]

# Low stock alert automation.
#
# Any document whose submission or cancellation can change a Bin's
# actual_qty is hooked here on both on_submit and on_cancel, because
# either direction (adding or removing stock) can cross the low-stock
# threshold for an "important" item. Stock Ledger Entry / Bin writes
# performed internally by these controllers via db_insert do not reliably
# emit their own DocType events, so the real originating transaction is
# hooked instead. See synthetic_build_target_app.stock_alerts for the
# threshold check and Notification Log creation, which is deliberately
# deferred to a frappe.db.after_commit callback so it only runs once
# this transaction's database changes have actually committed.
#
# Sales Invoice already carries an on_submit hook (see
# synthetic_build_target_app.sales_invoice_project) that creates a linked
# Project for every submitted invoice; the low-stock check is appended as
# a second on_submit handler (Frappe invokes every handler in the list)
# rather than replacing it, so both pieces of already-landed behavior run.
doc_events = {
    "Sales Invoice": {
        "on_submit": [
            "synthetic_build_target_app.sales_invoice_project.create_project_for_submitted_sales_invoice",
            "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
        ],
        "on_cancel": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
    },
    "Delivery Note": {
        "on_submit": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
    },
    "Purchase Receipt": {
        "on_submit": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
    },
    "Purchase Invoice": {
        "on_submit": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
    },
    "Stock Entry": {
        "on_submit": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
    },
    "Stock Reconciliation": {
        "on_submit": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
        "on_cancel": "synthetic_build_target_app.stock_alerts.queue_low_stock_check",
    },
}
