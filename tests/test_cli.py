from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vocab_shell.cli import VocabCompleter, VocabShell

try:
    from prompt_toolkit.document import Document

    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False


class CliOutputShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.home = Path(self.tempdir.name)
        self.env_patch = patch.dict(os.environ, {"VOCAB_SHELL_HOME": str(self.home)})
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.tempdir.cleanup()

    def test_attach_examples_to_definitions_groups_examples(self) -> None:
        groups = VocabShell._attach_examples_to_definitions(
            ["meaning 1", "meaning 2"],
            ["example 1", "example 2", "example 3"],
        )
        self.assertEqual(groups, [["example 1", "example 3"], ["example 2"]])

    def test_attach_examples_to_definitions_handles_missing_examples(self) -> None:
        groups = VocabShell._attach_examples_to_definitions(["meaning 1"], [])
        self.assertEqual(groups, [[]])

    def test_highlight_exact_word_in_sentence(self) -> None:
        shell = VocabShell()
        line = shell._highlight_exact_word("He chose to abandon the plan.", "abandon")
        expected = f"{shell.theme['highlight_start']}abandon{shell.theme['highlight_end']}"
        self.assertIn(expected, line)

    def test_highlight_does_not_match_partial_word(self) -> None:
        shell = VocabShell()
        line = shell._highlight_exact_word("He was abandoned quickly.", "abandon")
        expected = f"{shell.theme['highlight_start']}abandon{shell.theme['highlight_end']}"
        self.assertNotIn(expected, line)

    def test_colorize_meaning_wraps_with_meaning_color(self) -> None:
        shell = VocabShell()
        line = shell._colorize_meaning("to leave behind")
        self.assertEqual(
            line,
            f"{shell.theme['meaning_start']}to leave behind{shell.theme['color_end']}",
        )

    def test_format_example_line_colors_pos_tag(self) -> None:
        shell = VocabShell()
        line = shell._format_example_line("[VERB] He abandoned the car.", "abandon")
        self.assertIn(f"{shell.theme['pos_start']}[VERB]{shell.theme['color_end']}", line)

    def test_creates_default_theme_file(self) -> None:
        shell = VocabShell()
        theme_path = self.home / "theme.json"
        self.assertTrue(theme_path.exists())
        payload = json.loads(theme_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["active_profile"], "auto")
        self.assertIn("dark", payload["profiles"])
        self.assertIn("light", payload["profiles"])
        self.assertEqual(shell.theme["color_end"], "\033[0m")

    def test_loads_custom_theme_values(self) -> None:
        custom = {
            "active_profile": "dark",
            "profiles": {
                "dark": {
                    "highlight": {"fg": "#ff0000", "bold": True},
                    "meaning": {"fg": "#ffffff", "bold": True},
                    "pos": {"fg": "#000000", "bg": "#ffffff", "bold": True},
                },
                "light": {
                    "highlight": {"fg": "#7a0000", "bold": True},
                    "meaning": {"fg": "#003366", "bold": True},
                    "pos": {"fg": "#000000", "bg": "#dddddd", "bold": True},
                },
            },
        }
        (self.home / "theme.json").write_text(
            json.dumps(custom, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        shell = VocabShell()
        self.assertEqual(shell.theme["highlight_start"], "\033[1;38;2;255;0;0m")
        self.assertEqual(shell.theme["meaning_start"], "\033[1;38;2;255;255;255m")
        self.assertEqual(shell.theme["pos_start"], "\033[1;38;2;0;0;0;48;2;255;255;255m")

    @unittest.skipUnless(HAS_PROMPT_TOOLKIT, "prompt_toolkit is required for completion tests")
    def test_completer_suggests_matching_commands(self) -> None:
        shell = VocabShell()
        completer = VocabCompleter(shell)
        completions = list(completer.get_completions(Document("s"), None))
        texts = [item.text for item in completions]
        self.assertIn("search", texts)
        self.assertIn("stats", texts)

    @unittest.skipUnless(HAS_PROMPT_TOOLKIT, "prompt_toolkit is required for completion tests")
    def test_completer_suggests_recent_search_history(self) -> None:
        shell = VocabShell()
        shell.search_history = ["abandon", "ability", "zebra"]
        completer = VocabCompleter(shell)
        completions = list(completer.get_completions(Document("search a"), None))
        texts = [item.text for item in completions]
        self.assertEqual(texts, ["abandon", "ability"])

    @unittest.skipUnless(HAS_PROMPT_TOOLKIT, "prompt_toolkit is required for completion tests")
    def test_completer_suggests_dict_subcommands(self) -> None:
        shell = VocabShell()
        completer = VocabCompleter(shell)
        completions = list(completer.get_completions(Document("dict "), None))
        texts = [item.text for item in completions]
        self.assertEqual(texts, ["create", "list"])

    @unittest.skipUnless(HAS_PROMPT_TOOLKIT, "prompt_toolkit is required for completion tests")
    def test_completer_suggests_dictionary_for_stats_and_review(self) -> None:
        shell = VocabShell()
        shell.storage.create_dictionary("toefl-core")
        shell.storage.create_dictionary("daily")
        completer = VocabCompleter(shell)

        stats_completions = list(completer.get_completions(Document("stats t"), None))
        stats_texts = [item.text for item in stats_completions]
        self.assertEqual(stats_texts, ["toefl-core"])

        review_completions = list(completer.get_completions(Document("review d"), None))
        review_texts = [item.text for item in review_completions]
        self.assertEqual(review_texts, ["daily"])

    @unittest.skipUnless(HAS_PROMPT_TOOLKIT, "prompt_toolkit is required for completion tests")
    def test_completer_suggests_review_count(self) -> None:
        shell = VocabShell()
        completer = VocabCompleter(shell)
        completions = list(completer.get_completions(Document("review deck 1"), None))
        texts = [item.text for item in completions]
        self.assertEqual(texts, ["10"])

    def test_completer_limits_search_history_to_ten_entries(self) -> None:
        shell = VocabShell()
        for idx in range(12):
            shell._remember_search(f"word-{idx}")
        self.assertEqual(len(shell.search_history), 10)
        self.assertEqual(shell.search_history[0], "word-11")

    @unittest.skipUnless(HAS_PROMPT_TOOLKIT, "prompt_toolkit is required for picker tests")
    def test_choose_dictionary_with_arrows_uses_prompt_completion_result(self) -> None:
        shell = VocabShell()

        class DummyPromptSession:
            @staticmethod
            def prompt(*args, **kwargs) -> str:
                return "toefl-core"

        dictionaries = [{"name": "toefl-core"}, {"name": "daily"}]
        shell.prompt_session = DummyPromptSession()
        selected = shell._choose_dictionary_with_arrows(dictionaries)
        self.assertEqual(selected, "toefl-core")


if __name__ == "__main__":
    unittest.main()
