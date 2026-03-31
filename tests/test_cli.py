from __future__ import annotations

import unittest

from vocab_shell.cli import VocabShell


class CliOutputShapeTests(unittest.TestCase):
    def test_attach_examples_to_definitions_groups_examples(self) -> None:
        groups = VocabShell._attach_examples_to_definitions(
            ["meaning 1", "meaning 2"],
            ["example 1", "example 2", "example 3"],
        )
        self.assertEqual(groups, [["example 1", "example 3"], ["example 2"]])

    def test_attach_examples_to_definitions_handles_missing_examples(self) -> None:
        groups = VocabShell._attach_examples_to_definitions(["meaning 1"], [])
        self.assertEqual(groups, [[]])


if __name__ == "__main__":
    unittest.main()
