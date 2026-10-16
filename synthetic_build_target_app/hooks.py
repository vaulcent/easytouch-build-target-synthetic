app_name = "synthetic_build_target_app"
app_title = "Synthetic Build Target App"
app_publisher = "Easytouch Test"
app_description = "Fabricated disposable Frappe app used only as a D1 GitHub integration target"
app_email = "fixture@example.test"
app_license = "MIT"

fixtures = [
    "Custom Field",
    # The "Selling Rate Override" Role is the authorized-override-role
    # metadata for the Sales Invoice selling-rate-vs-valuation-rate
    # validation below. Filtered so only this one Role record is exported,
    # never the whole Role table.
    {
        "dt": "Role",
        "filters": [["name", "=", "Selling Rate Override"]],
    },
]

# Every time a submitted Sales Invoice is created, automatically create a
# Project for that invoice using the customer name and invoice number.
# The handler is idempotent: on_submit retries (or any re-invocation of the
# same event for the same invoice) must never create a duplicate Project.
#
# Also, before a Sales Invoice can be saved/submitted, block it when any
# line's selling rate (converted to Company currency, per Stock UOM) is
# below that item's valuation rate -- unless the acting user holds the
# "Selling Rate Override" role.
doc_events = {
    "Sales Invoice": {
        "validate": "synthetic_build_target_app.sales_invoice_rate_validation.validate_selling_rate_against_valuation",
        "on_submit": "synthetic_build_target_app.sales_invoice_events.create_project_from_sales_invoice",
    }
}
