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
    # Workflow State / Workflow Action Master masters referenced by the
    # Sales Order discount-approval Workflow below. Filtered so only the
    # records this Workflow actually uses are exported -- never the whole
    # (shared) table, since other apps/workflows may define their own
    # states/actions on the same site.
    {
        "dt": "Workflow State",
        "filters": [["name", "in", ["Draft", "Pending Manager Approval", "Approved"]]],
    },
    {
        "dt": "Workflow Action Master",
        "filters": [["name", "in", ["Submit", "Send for Approval", "Approve"]]],
    },
    # Sales Order discount-approval Workflow.
    #
    # Requirement: salespeople must not be able to approve big discounts
    # themselves. If a Sales Order's additional_discount_percentage is
    # more than 10, it must go to a Sales Manager for approval instead of
    # being submittable directly by the salesperson.
    #
    # States: "Draft" (docstatus 0, edited by the "Sales User" role) ->
    # either "Approved" (docstatus 1) directly when discount <= 10, or
    # "Pending Manager Approval" (docstatus 0, edited by "Sales Manager")
    # when discount > 10 -> "Approved" (docstatus 1).
    #
    # The Draft -> Approved "Submit" transition (discount <= 10) is an
    # ordinary self-submit by the Sales User who owns the order, so
    # allow_self_approval is left at its default (1) there.
    #
    # The Pending Manager Approval -> Approved "Approve" transition is the
    # one that must be independent of its requester: allow_self_approval
    # is explicitly 0, so a Sales Manager who also happens to own/have
    # created the order being approved is still denied by Frappe's own
    # apply_workflow() self-approval rule, and only a *different* Sales
    # Manager can complete that approval.
    {
        "dt": "Workflow",
        "filters": [["name", "=", "Sales Order Discount Approval"]],
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

# Idempotently install the minimal Sales Order read/write/create/submit
# permissions that the discount-approval Workflow above requires for its
# "Sales User" and "Sales Manager" actors, derived directly from that
# workflow's own transition matrix: both the salesperson self-submit
# transition (Draft -> Approved) and the manager Approve transition
# (Pending Manager Approval -> Approved) perform a real docstatus 0 -> 1
# submit, so both roles need live submit permission on Sales Order. This
# grant lives in deployable app lifecycle code (after_migrate), never
# inside the behavior tests themselves.
after_migrate = [
    "synthetic_build_target_app.sales_order_discount_workflow_permissions.ensure_discount_approval_permissions",
]
