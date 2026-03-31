from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import textwrap
from datetime import UTC, datetime
from pathlib import Path

from vocab_shell.collins import CollinsClient, CollinsError
from vocab_shell.models import ReviewState, SavedWord
from vocab_shell.review import ReviewError, ReviewManager
from vocab_shell.storage import Storage, StorageError


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
        self.theme = self._load_color_theme(self.theme_path)
        self.review_manager = ReviewManager(self.storage)

    def run(self) -> int:
        print("Vocab Shell")
        print("Type 'help' for commands.\n")
        while True:
            try:
                raw = input("vocab> ").strip()
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
        print(f"Word: {self._highlight_exact_word(query, query)}")
        print(f"Dictionary: {entry.dictionary_code}")
        grouped_examples = entry.meaning_examples
        if len(grouped_examples) != len(entry.definitions):
            grouped_examples = self._attach_examples_to_definitions(entry.definitions, entry.examples)
        for idx, definition in enumerate(entry.definitions, start=1):
            print(f"  {idx}. {self._colorize_meaning(definition)}")
            if grouped_examples[idx - 1]:
                for ex_idx, example in enumerate(grouped_examples[idx - 1], start=1):
                    max_content_width = self._get_box_max_content_width(indent="     ")
                    formatted = self._prepare_example_lines_for_box(example, query, max_content_width)
                    box = self._render_box(
                        title=f"Example {idx}.{ex_idx}",
                        lines=formatted,
                        indent="     ",
                        max_width=max_content_width,
                    )
                    for line in box:
                        print(line)
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
    def _render_box(
        cls, title: str, lines: list[str], indent: str = "", min_width: int = 32, max_width: int | None = None
    ) -> list[str]:
        visible_width = max((cls._visible_len(line) for line in lines), default=0)
        content_width = max(visible_width + 4, min_width)
        if max_width is not None:
            content_width = min(content_width, max_width)
        title_text = f"{title}"
        title_len = cls._visible_len(title_text)
        bar_len = max(content_width - title_len, 0)
        top = f"{indent}╭{title_text}{'─' * bar_len}╮"
        body: list[str] = [f"{indent}│{' ' * content_width}│"]
        for line in lines:
            pad = content_width - cls._visible_len(line) - 2
            body.append(f"{indent}│  {line}{' ' * max(pad, 0)}│")
        body.append(f"{indent}│{' ' * content_width}│")
        bottom = f"{indent}╰{'─' * content_width}╯"
        return [top, *body, bottom]

    @staticmethod
    def _get_box_max_content_width(indent: str, min_width: int = 32) -> int:
        term_width = shutil.get_terminal_size(fallback=(100, 20)).columns
        return max(term_width - len(indent) - 2, min_width)

    def _prepare_example_lines_for_box(self, text: str, query: str, content_width: int) -> list[str]:
        line_limit = max(content_width - 2, 16)
        match = re.match(r"^(\[[^\]]+\])\s*(.*)$", text.strip())
        if match:
            pos, body = match.groups()
            first_chunk_width = max(line_limit - len(pos) - 1, 12)
            chunks = textwrap.wrap(
                body,
                width=first_chunk_width,
                break_long_words=False,
                break_on_hyphens=False,
            ) or [body]
            first = self._highlight_exact_word(chunks[0], query)
            pos_colored = f"{self.theme['pos_start']}{pos}{self.theme['color_end']}"
            lines = [f"{pos_colored} {first}".rstrip()]
            if len(chunks) > 1:
                follow = textwrap.wrap(
                    " ".join(chunks[1:]),
                    width=line_limit,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                lines.extend(self._highlight_exact_word(chunk, query) for chunk in follow)
            return lines

        chunks = textwrap.wrap(
            text,
            width=line_limit,
            break_long_words=False,
            break_on_hyphens=False,
        ) or [text]
        return [self._highlight_exact_word(chunk, query) for chunk in chunks]

    @staticmethod
    def _strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    @classmethod
    def _visible_len(cls, text: str) -> int:
        return len(cls._strip_ansi(text))

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
        upcoming = sorted(words, key=lambda item: item.review.next_review_at)[:5]
        if upcoming:
            print("Next reviews:")
            for word in upcoming:
                print(f"  {word.word}: {word.review.next_review_at} (stage {word.review.stage_index})")
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
