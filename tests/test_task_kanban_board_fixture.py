import json
import os
import unittest

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "fixtures",
    "kanban_board.json",
)

HOOKS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "synthetic_build_target_app",
    "hooks.py",
)

EXPECTED_COLUMN_NAMES = [
    "Open",
    "Working",
    "Pending Review",
    "Completed",
    "Overdue",
    "Cancelled",
    "Template",
]


class TestTaskKanbanBoardFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            cls.fixtures = json.load(handle)

    def _task_kanban_board_entries(self):
        return [
            entry
            for entry in self.fixtures
            if entry.get("doctype") == "Kanban Board"
            and entry.get("reference_doctype") == "Task"
        ]

    def test_fixture_file_is_a_list(self):
        self.assertIsInstance(self.fixtures, list)

    def test_task_kanban_board_exists_exactly_once(self):
        entries = self._task_kanban_board_entries()
        self.assertEqual(
            len(entries),
            1,
            "Expected exactly one 'Kanban Board' fixture for Task "
            "(idempotent - no duplicates).",
        )

    def test_task_kanban_board_definition(self):
        entry = self._task_kanban_board_entries()[0]
        self.assertEqual(entry["name"], "Task Kanban")
        self.assertEqual(entry["kanban_board_name"], "Task Kanban")
        self.assertEqual(entry["reference_doctype"], "Task")
        self.assertEqual(entry["field_name"], "status")

    def test_task_kanban_board_columns_cover_drag_states(self):
        entry = self._task_kanban_board_entries()[0]
        columns = entry.get("columns", [])
        column_names = [column["column_name"] for column in columns]
        self.assertEqual(column_names, EXPECTED_COLUMN_NAMES)
        for column in columns:
            self.assertEqual(column["doctype"], "Kanban Board Column")
            self.assertIn("indicator", column)

    def test_no_duplicate_kanban_board_names(self):
        seen = set()
        for entry in self.fixtures:
            if entry.get("doctype") != "Kanban Board":
                continue
            name = entry.get("name")
            self.assertNotIn(name, seen, f"Duplicate Kanban Board fixture: {name}")
            seen.add(name)

    def test_hooks_register_kanban_board_fixture(self):
        with open(HOOKS_PATH, "r", encoding="utf-8") as handle:
            hooks_source = handle.read()
        namespace = {}
        exec(compile(hooks_source, HOOKS_PATH, "exec"), namespace)
        self.assertIn("fixtures", namespace)
        self.assertIn("Custom Field", namespace["fixtures"])
        self.assertIn("Kanban Board", namespace["fixtures"])


if __name__ == "__main__":
    unittest.main()
