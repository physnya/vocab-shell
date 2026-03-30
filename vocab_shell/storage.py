from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from vocab_shell.models import ReviewHistoryItem, ReviewState, SavedWord


def utcnow() -> datetime:
    return datetime.now(UTC)


class StorageError(RuntimeError):
    pass


class Storage:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.dictionaries_dir = self.home / "dictionaries"
        self.config_path = self.home / "config.json"
        self.home.mkdir(parents=True, exist_ok=True)
        self.dictionaries_dir.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self._write_json(self.config_path, {"created_at": utcnow().isoformat()})

    def create_dictionary(self, name: str) -> Path:
        slug = self.normalize_dictionary_name(name)
        path = self.dictionary_path(slug)
        if path.exists():
            raise StorageError(f"Dictionary '{slug}' already exists.")
        payload = {
            "name": slug,
            "created_at": utcnow().isoformat(),
            "words": {},
        }
        self._write_json(path, payload)
        return path

    def list_dictionaries(self) -> list[dict]:
        items = []
        for path in sorted(self.dictionaries_dir.glob("*.json")):
            data = self._read_json(path)
            words = data.get("words", {})
            due_count = 0
            now = utcnow()
            for item in words.values():
                next_review_at = self._parse_datetime(item["review"]["next_review_at"])
                if next_review_at <= now:
                    due_count += 1
            items.append(
                {
                    "name": data["name"],
                    "created_at": data["created_at"],
                    "word_count": len(words),
                    "due_count": due_count,
                }
            )
        return items

    def dictionary_exists(self, name: str) -> bool:
        return self.dictionary_path(name).exists()

    def add_word(self, dictionary_name: str, word: SavedWord) -> None:
        data = self.load_dictionary(dictionary_name)
        key = word.word.lower()
        data["words"][key] = asdict(word)
        self._write_json(self.dictionary_path(dictionary_name), data)

    def load_dictionary(self, name: str) -> dict:
        path = self.dictionary_path(name)
        if not path.exists():
            raise StorageError(f"Dictionary '{name}' does not exist.")
        return self._read_json(path)

    def save_dictionary(self, name: str, payload: dict) -> None:
        self._write_json(self.dictionary_path(name), payload)

    def dictionary_path(self, name: str) -> Path:
        return self.dictionaries_dir / f"{self.normalize_dictionary_name(name)}.json"

    @staticmethod
    def normalize_dictionary_name(name: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
        if not cleaned:
            raise StorageError("Dictionary name cannot be empty.")
        return cleaned

    @staticmethod
    def hydrate_saved_word(payload: dict) -> SavedWord:
        history = [
            ReviewHistoryItem(
                reviewed_at=item["reviewed_at"],
                correct=item["correct"],
                chosen_answer=item["chosen_answer"],
                correct_answer=item["correct_answer"],
            )
            for item in payload["review"].get("history", [])
        ]
        review = ReviewState(
            stage_index=payload["review"]["stage_index"],
            next_review_at=payload["review"]["next_review_at"],
            last_reviewed_at=payload["review"].get("last_reviewed_at"),
            history=history,
        )
        return SavedWord(
            word=payload["word"],
            added_at=payload["added_at"],
            definitions=payload["definitions"],
            examples=payload["examples"],
            source_dictionary_code=payload["source_dictionary_code"],
            source_entry_id=payload.get("source_entry_id"),
            source_entry_url=payload.get("source_entry_url"),
            review=review,
        )

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @staticmethod
    def _read_json(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
