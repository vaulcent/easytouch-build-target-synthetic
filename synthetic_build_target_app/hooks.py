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

fixtures = ["Custom Field"]

# Server-side validation lanes that prevent submitting a Sales Invoice when
# any item's selling rate is below its valuation rate, unless the acting
# user holds the "Sales Invoice Rate Override" role. Both the "validate"
# (save-time, early feedback) and "before_submit" (hard stop before
# submission) lanes call the same idempotent validation function so the
# rule cannot drift out of sync between the two lanes.
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
    }
}
