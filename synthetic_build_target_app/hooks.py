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
