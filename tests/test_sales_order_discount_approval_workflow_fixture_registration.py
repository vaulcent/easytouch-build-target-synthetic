"""Dependency-free static check that the Sales Order discount-approval
Workflow fixtures/permissions wiring exist in hooks.py.

This test does NOT require Frappe and is not, by itself, ERP behavior
evidence. The authoritative ERP-backed behavior proof lives in
tests/test_sales_order_discount_approval_workflow.py (marked with
EASYTOUCH_ERP_BEHAVIOR_KINDS = ('workflow',)).
"""
import importlib
import json
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


class SalesOrderDiscountApprovalWorkflowRegistrationTests(unittest.TestCase):
    def test_workflow_fixture_is_registered_in_hooks(self):
        hooks = importlib.import_module("synthetic_build_target_app.hooks")
        fixtures = getattr(hooks, "fixtures", [])
        workflow_entries = [
            f for f in fixtures
            if isinstance(f, dict) and f.get("dt") == "Workflow"
        ]
        self.assertTrue(workflow_entries, "A 'Workflow' fixture entry must be registered")
        self.assertIn(
            ["name", "=", "Sales Order Discount Approval"],
            workflow_entries[0]["filters"],
        )

    def test_after_migrate_installs_discount_approval_permissions(self):
        hooks = importlib.import_module("synthetic_build_target_app.hooks")
        after_migrate = getattr(hooks, "after_migrate", [])
        self.assertIn(
            "synthetic_build_target_app.sales_order_discount_workflow_permissions"
            ".ensure_discount_approval_permissions",
            after_migrate,
        )

    def test_permission_module_is_importable_without_frappe(self):
        module = importlib.import_module(
            "synthetic_build_target_app.sales_order_discount_workflow_permissions"
        )
        self.assertTrue(callable(module.ensure_discount_approval_permissions))
        self.assertEqual(module.DOCTYPE, "Sales Order")
        self.assertEqual(
            module.REQUIRED_PERMISSIONS["Sales User"],
            {"read": 1, "write": 1, "create": 1, "submit": 1},
        )
        self.assertEqual(
            module.REQUIRED_PERMISSIONS["Sales Manager"],
            {"read": 1, "write": 1, "create": 1, "submit": 1},
        )

    def test_workflow_fixture_file_defines_the_discount_threshold_transitions(self):
        path = os.path.join(
            REPO_ROOT, "synthetic_build_target_app", "fixtures", "workflow.json"
        )
        with open(path, "r", encoding="utf-8") as fh:
            workflows = json.load(fh)

        self.assertEqual(len(workflows), 1)
        workflow = workflows[0]
        self.assertEqual(workflow["document_type"], "Sales Order")
        self.assertEqual(workflow["is_active"], 1)

        transitions_by_action = {t["action"]: t for t in workflow["transitions"]}

        submit = transitions_by_action["Submit"]
        self.assertEqual(submit["state"], "Draft")
        self.assertEqual(submit["next_state"], "Approved")
        self.assertEqual(submit["allowed"], "Sales User")
        self.assertIn("<= 10", submit["condition"])

        send_for_approval = transitions_by_action["Send for Approval"]
        self.assertEqual(send_for_approval["next_state"], "Pending Manager Approval")
        self.assertIn("> 10", send_for_approval["condition"])

        approve = transitions_by_action["Approve"]
        self.assertEqual(approve["state"], "Pending Manager Approval")
        self.assertEqual(approve["next_state"], "Approved")
        self.assertEqual(approve["allowed"], "Sales Manager")
        self.assertEqual(approve["allow_self_approval"], 0)


if __name__ == "__main__":
    unittest.main()
