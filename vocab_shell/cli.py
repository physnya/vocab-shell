from __future__ import annotations

import json
import os
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from vocab_shell.collins import CollinsClient, CollinsError
from vocab_shell.models import ReviewState, SavedWord
from vocab_shell.review import ReviewError, ReviewManager
from vocab_shell.storage import Storage, StorageError

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.shortcuts import CompleteStyle

    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False
    Completer = object
    if TYPE_CHECKING:
        from prompt_toolkit.completion import Completion
        from prompt_toolkit.document import Document


class VocabCompleter(Completer):
    COMMANDS = ("search", "stats", "review", "dict", "help", "quit", "exit")
    REVIEW_COUNTS = ("5", "10", "20", "30", "50")

    def __init__(self, shell: "VocabShell") -> None:
        self.shell = shell

    def get_completions(self, document: "Document", complete_event):
        text = document.text_before_cursor
        stripped = text.lstrip()

        if not stripped:
            for command in self.COMMANDS:
                yield Completion(command, start_position=0)
            return

        parts = stripped.split()
        cursor_at_new_token = text.endswith(" ")
        current = "" if cursor_at_new_token else parts[-1]
        if cursor_at_new_token:
            parts.append("")

        if len(parts) == 1:
            for command in self._filter_commands(current):
                yield Completion(command, start_position=-len(current))
            return

        command = parts[0]
        if command == "search":
            prefix = stripped[len("search") :].lstrip()
            for term in self._filter_search_history(prefix):
                yield Completion(term, start_position=-len(prefix), display_meta="history")
            return

        if command == "dict":
            if len(parts) == 2:
                for option in ("create", "list"):
                    if option.startswith(current):
                        yield Completion(option, start_position=-len(current), display_meta="subcommand")
            return

        if command == "stats":
            if len(parts) == 2:
                for name in self._filter_dictionary_names(current):
                    yield Completion(name, start_position=-len(current), display_meta="dictionary")
            return

        if command == "review":
            if len(parts) == 2:
                for name in self._filter_dictionary_names(current):
                    yield Completion(name, start_position=-len(current), display_meta="dictionary")
                return
            if len(parts) == 3:
                for count in self._filter_review_counts(current):
                    yield Completion(count, start_position=-len(current), display_meta="count")
            return

    def _filter_commands(self, prefix: str) -> list[str]:
        return [command for command in self.COMMANDS if command.startswith(prefix)]

    def _filter_search_history(self, prefix: str) -> list[str]:
        prefix_lower = prefix.lower()
        return [term for term in self.shell.search_history if term.lower().startswith(prefix_lower)]

    def _filter_dictionary_names(self, prefix: str) -> list[str]:
        return [
            name
            for name in self.shell.list_dictionary_names_for_completion()
            if name.startswith(prefix)
        ]

    def _filter_review_counts(self, prefix: str) -> list[str]:
        return [value for value in self.REVIEW_COUNTS if value.startswith(prefix)]


class VocabShell:
    DEFAULT_THEME = {
        "highlight_start": "\033[1;4;35m",
        "highlight_end": "\033[0m",
        "meaning_start": "\033[1;96m",
        "pos_start": "\033[1;7m",
        "color_end": "\033[0m",
    }
    DEFAULT_THEME_CONFIG = {
        "active_profile": "auto",
        "profiles": {
            "dark": {
                "highlight": {"fg": "#ff5fd7", "bold": True, "underline": True},
                "meaning": {"fg": "#66ffff", "bold": True},
                "pos": {"fg": "#101010", "bg": "#ffe082", "bold": True},
            },
            "light": {
                "highlight": {"fg": "#8a005c", "bold": True, "underline": True},
                "meaning": {"fg": "#005a9c", "bold": True},
                "pos": {"fg": "#000000", "bg": "#ffd54f", "bold": True},
            },
        },
    }

    def __init__(self) -> None:
        custom_home = os.getenv("VOCAB_SHELL_HOME")
        if custom_home:
            home = Path(custom_home).expanduser()
        else:
            home = Path.cwd() / ".vocab-shell"
        self.storage = Storage(home)
        self.theme_path = self.storage.home / "theme.json"
        self.search_history_path = self.storage.home / "search_history.json"
        self.theme = self._load_color_theme(self.theme_path)
        self.review_manager = ReviewManager(self.storage)
        self.search_history = self._load_search_history()
        self.prompt_session = self._create_prompt_session()

    def run(self) -> int:
        print("Vocab Shell")
        print("Type 'help' for commands.\n")
        while True:
            try:
                raw = self._prompt("vocab> ").strip()
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print()
                continue

            if not raw:
                continue

            try:
                should_exit = self.handle_command(raw)
            except (StorageError, CollinsError, ReviewError) as exc:
                print(f"Error: {exc}\n")
                continue
            except KeyboardInterrupt:
                print("\nCancelled.\n")
                continue

            if should_exit:
                return 0

    def handle_command(self, raw: str) -> bool:
        parts = shlex.split(raw)
        command = parts[0].lower()

        if command in {"quit", "exit"}:
            return True
        if command == "help":
            self.print_help()
            return False
        if command == "search":
            if len(parts) < 2:
                raise StorageError("Usage: search <word>")
            self.search_word(" ".join(parts[1:]))
            return False
        if command == "dict":
            self.handle_dict_command(parts[1:])
            return False
        if command == "review":
            if len(parts) != 3:
                raise StorageError("Usage: review <dictionary-name> <count>")
            self.review(parts[1], int(parts[2]))
            return False
        if command == "stats":
            if len(parts) != 2:
                raise StorageError("Usage: stats <dictionary-name>")
            self.print_stats(parts[1])
            return False

        raise StorageError(f"Unknown command '{command}'. Type 'help' for commands.")

    def search_word(self, word: str) -> None:
        client = CollinsClient()
        entry = client.search(word)
        query = word.strip()
        self._remember_search(query)
        print(f"Word: {self._highlight_exact_word(query, query)}")
        print(f"Dictionary: {entry.dictionary_code}")
        grouped_examples = entry.meaning_examples
        if len(grouped_examples) != len(entry.definitions):
            grouped_examples = self._attach_examples_to_definitions(entry.definitions, entry.examples)
        for idx, definition in enumerate(entry.definitions, start=1):
            print(f"  {idx}. {self._colorize_meaning(definition)}")
            if grouped_examples[idx - 1]:
                print("     Examples:")
                for ex_idx, example in enumerate(grouped_examples[idx - 1], start=1):
                    formatted = self._format_example_line(example, query)
                    print(f"       {ex_idx}) {formatted}")
        print()
        self.offer_to_save(entry)

    def _highlight_exact_word(self, text: str, word: str) -> str:
        needle = word.strip()
        if not needle:
            return text
        pattern = re.compile(rf"\b({re.escape(needle)})\b", flags=re.IGNORECASE)
        return pattern.sub(
            rf"{self.theme['highlight_start']}\1{self.theme['highlight_end']}",
            text,
        )

    def _colorize_meaning(self, text: str) -> str:
        return f"{self.theme['meaning_start']}{text}{self.theme['color_end']}"

    def _format_example_line(self, text: str, query: str) -> str:
        match = re.match(r"^(\[[^\]]+\])\s*(.*)$", text.strip())
        if match:
            pos, body = match.groups()
            body = self._highlight_exact_word(body, query)
            return f"{self.theme['pos_start']}{pos}{self.theme['color_end']} {body}".rstrip()
        return self._highlight_exact_word(text, query)

    @classmethod
    def _load_color_theme(cls, path: Path) -> dict[str, str]:
        theme = dict(cls.DEFAULT_THEME)
        if not path.exists():
            cls._write_theme(path, cls.DEFAULT_THEME_CONFIG)
            return cls._resolve_theme_from_config(cls.DEFAULT_THEME_CONFIG)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cls._write_theme(path, cls.DEFAULT_THEME_CONFIG)
            return cls._resolve_theme_from_config(cls.DEFAULT_THEME_CONFIG)

        if cls._is_flat_theme(payload):
            for key, value in payload.items():
                if key in theme and isinstance(value, str):
                    theme[key] = value
            return theme

        config = cls._normalize_theme_config(payload)
        if payload != config:
            cls._write_theme(path, config)
        return cls._resolve_theme_from_config(config)

    @staticmethod
    def _write_theme(path: Path, payload: dict) -> None:
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _is_flat_theme(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        return any(key.endswith("_start") or key.endswith("_end") for key in payload.keys())

    @classmethod
    def _normalize_theme_config(cls, payload: object) -> dict:
        config = json.loads(json.dumps(cls.DEFAULT_THEME_CONFIG))
        if not isinstance(payload, dict):
            return config

        active = payload.get("active_profile")
        if isinstance(active, str) and active in {"auto", "dark", "light"}:
            config["active_profile"] = active

        profiles = payload.get("profiles")
        if not isinstance(profiles, dict):
            return config

        for profile_name in ("dark", "light"):
            raw_profile = profiles.get(profile_name)
            if not isinstance(raw_profile, dict):
                continue
            for key in ("highlight", "meaning", "pos"):
                raw_style = raw_profile.get(key)
                if isinstance(raw_style, (dict, str)):
                    config["profiles"][profile_name][key] = raw_style
        return config

    @classmethod
    def _resolve_theme_from_config(cls, config: dict) -> dict[str, str]:
        profile_name = config.get("active_profile", "auto")
        if profile_name == "auto":
            profile_name = cls._detect_terminal_profile()
        if profile_name not in {"dark", "light"}:
            profile_name = "dark"

        profile = config.get("profiles", {}).get(profile_name, {})
        theme = dict(cls.DEFAULT_THEME)
        highlight = cls._style_to_escape(profile.get("highlight"))
        meaning = cls._style_to_escape(profile.get("meaning"))
        pos = cls._style_to_escape(profile.get("pos"))
        if highlight:
            theme["highlight_start"] = highlight
        if meaning:
            theme["meaning_start"] = meaning
        if pos:
            theme["pos_start"] = pos
        return theme

    @staticmethod
    def _detect_terminal_profile() -> str:
        colorfgbg = os.getenv("COLORFGBG", "")
        tokens = re.findall(r"\d+", colorfgbg)
        if not tokens:
            return "dark"
        background = int(tokens[-1])
        return "light" if background >= 7 else "dark"

    @classmethod
    def _style_to_escape(cls, style: object) -> str | None:
        if isinstance(style, str):
            if style.startswith("\033["):
                return style
            return None
        if not isinstance(style, dict):
            return None

        codes: list[str] = []
        if style.get("bold"):
            codes.append("1")
        if style.get("underline"):
            codes.append("4")
        if style.get("reverse"):
            codes.append("7")

        fg = cls._parse_rgb_triplet(style.get("fg"))
        if fg:
            codes.append(f"38;2;{fg[0]};{fg[1]};{fg[2]}")
        bg = cls._parse_rgb_triplet(style.get("bg"))
        if bg:
            codes.append(f"48;2;{bg[0]};{bg[1]};{bg[2]}")

        if not codes:
            return None
        return f"\033[{';'.join(codes)}m"

    @staticmethod
    def _parse_rgb_triplet(value: object) -> tuple[int, int, int] | None:
        if isinstance(value, str):
            match = re.fullmatch(r"#?([0-9a-fA-F]{6})", value.strip())
            if not match:
                return None
            hex_code = match.group(1)
            return tuple(int(hex_code[idx : idx + 2], 16) for idx in (0, 2, 4))
        if isinstance(value, list) and len(value) == 3 and all(isinstance(item, int) for item in value):
            r, g, b = value
            if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                return (r, g, b)
        return None

    @staticmethod
    def _attach_examples_to_definitions(
        definitions: list[str], examples: list[str]
    ) -> list[list[str]]:
        groups = [[] for _ in definitions]
        if not definitions or not examples:
            return groups

        seed_count = min(len(definitions), len(examples))
        for idx in range(seed_count):
            groups[idx].append(examples[idx])

        for idx in range(seed_count, len(examples)):
            groups[idx % len(definitions)].append(examples[idx])
        return groups

    def _create_prompt_session(self):
        if not HAS_PROMPT_TOOLKIT:
            return None
        history_path = self.storage.home / ".shell_history"
        return PromptSession(
            history=FileHistory(str(history_path)),
            completer=VocabCompleter(self),
            auto_suggest=AutoSuggestFromHistory(),
            complete_while_typing=False,
            complete_style=CompleteStyle.COLUMN,
        )

    def _prompt(self, message: str) -> str:
        if self.prompt_session is None:
            return input(message)
        return self.prompt_session.prompt(message)

    def _load_search_history(self) -> list[str]:
        if not self.search_history_path.exists():
            return []
        try:
            payload = json.loads(self.search_history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        terms = [item for item in payload if isinstance(item, str) and item.strip()]
        return terms[:10]

    def _save_search_history(self) -> None:
        try:
            self.search_history_path.write_text(
                json.dumps(self.search_history, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def _remember_search(self, word: str) -> None:
        term = word.strip()
        if not term:
            return
        self.search_history = [item for item in self.search_history if item != term]
        self.search_history.insert(0, term)
        self.search_history = self.search_history[:10]
        self._save_search_history()

    def list_dictionary_names_for_completion(self) -> list[str]:
        try:
            return [item["name"] for item in self.storage.list_dictionaries()]
        except StorageError:
            return []

    def offer_to_save(self, entry) -> None:
        dictionaries = self.storage.list_dictionaries()
        if not dictionaries:
            print("No dictionaries exist yet. Create one with 'dict create <name>'.\n")
            return

        answer = input("Add this word to one of your dictionaries? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print()
            return

        print("Available dictionaries:")
        for idx, item in enumerate(dictionaries, start=1):
            print(f"  {idx}. {item['name']}")

        choice = input("Choose a dictionary by number or name: ").strip()
        target = self._resolve_dictionary_choice(choice, dictionaries)
        saved = SavedWord(
            word=entry.word,
            added_at=datetime.now(UTC).isoformat(),
            definitions=entry.definitions,
            examples=entry.examples,
            source_dictionary_code=entry.dictionary_code,
            source_entry_id=entry.raw_entry_id,
            source_entry_url=entry.raw_entry_url,
            review=ReviewState(),
        )
        self.storage.add_word(target, saved)
        print(f"Saved '{entry.word}' to '{target}'.\n")

    @staticmethod
    def _resolve_dictionary_choice(choice: str, dictionaries: list[dict]) -> str:
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(dictionaries):
                return dictionaries[index]["name"]
        normalized = Storage.normalize_dictionary_name(choice)
        for item in dictionaries:
            if item["name"] == normalized:
                return normalized
        raise StorageError("Invalid dictionary choice.")

    def handle_dict_command(self, args: list[str]) -> None:
        if not args:
            raise StorageError("Usage: dict create <name> | dict list")
        subcommand = args[0].lower()
        if subcommand == "create":
            if len(args) != 2:
                raise StorageError("Usage: dict create <name>")
            path = self.storage.create_dictionary(args[1])
            print(f"Created dictionary '{path.stem}'.\n")
            return
        if subcommand == "list":
            dictionaries = self.storage.list_dictionaries()
            if not dictionaries:
                print("No dictionaries found.\n")
                return
            for item in dictionaries:
                print(
                    f"{item['name']}: {item['word_count']} word(s), "
                    f"{item['due_count']} due for review"
                )
            print()
            return
        raise StorageError("Usage: dict create <name> | dict list")

    def review(self, dictionary_name: str, count: int) -> None:
        normalized = Storage.normalize_dictionary_name(dictionary_name)
        result = self.review_manager.run_session(normalized, count)
        print(f"Review finished: {result['correct']}/{result['total']} correct.\n")

    def print_stats(self, dictionary_name: str) -> None:
        normalized = Storage.normalize_dictionary_name(dictionary_name)
        data = self.storage.load_dictionary(normalized)
        words = [self.storage.hydrate_saved_word(item) for item in data.get("words", {}).values()]
        due = sum(1 for word in words if datetime.fromisoformat(word.review.next_review_at) <= datetime.now(UTC))
        print(f"Dictionary: {normalized}")
        print(f"Words: {len(words)}")
        print(f"Due now: {due}")
        print()

    @staticmethod
    def print_help() -> None:
        print("Commands:")
        print("  search <word>")
        print("  dict create <name>")
        print("  dict list")
        print("  review <dictionary-name> <count>")
        print("  stats <dictionary-name>")
        print("  help")
        print("  quit\n")


def main() -> int:
    shell = VocabShell()
    return shell.run()
