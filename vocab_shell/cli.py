from __future__ import annotations

import shlex
from datetime import UTC, datetime
from pathlib import Path

from vocab_shell.collins import CollinsClient, CollinsError
from vocab_shell.models import ReviewState, SavedWord
from vocab_shell.review import ReviewError, ReviewManager
from vocab_shell.storage import Storage, StorageError


class VocabShell:
    def __init__(self) -> None:
        import os

        custom_home = os.getenv("VOCAB_SHELL_HOME")
        if custom_home:
            home = Path(custom_home).expanduser()
        else:
            home = Path.cwd() / ".vocab-shell"
        self.storage = Storage(home)
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
        print(f"Word: {entry.word}")
        print(f"Dictionary: {entry.dictionary_code}")
        print("Definitions:")
        for idx, definition in enumerate(entry.definitions, start=1):
            print(f"  {idx}. {definition}")
        if entry.examples:
            print("Examples:")
            for idx, example in enumerate(entry.examples, start=1):
                print(f"  {idx}. {example}")
        print()
        self.offer_to_save(entry)

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
