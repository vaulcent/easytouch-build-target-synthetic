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
doc_events = {
    "Sales Invoice": {
        "on_submit": "synthetic_build_target_app.sales_invoice_automation.create_project_on_submit"
    }
}
