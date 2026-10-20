app_name = "synthetic_build_target_app"
app_title = "Synthetic Build Target App"
app_publisher = "Easytouch Test"
app_description = "Fabricated disposable Frappe app used only as a D1 GitHub integration target"
app_email = "fixture@example.test"
app_license = "MIT"

fixtures = ["Custom Field"]

doc_events = {
    "Sales Invoice": {
        "on_submit": "synthetic_build_target_app.sales_invoice_project.create_project_for_submitted_sales_invoice",
    },
}
