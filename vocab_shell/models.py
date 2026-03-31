from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


DEFAULT_REVIEW_INTERVALS = [
    24 * 60 * 60,
    2 * 24 * 60 * 60,
    4 * 24 * 60 * 60,
    7 * 24 * 60 * 60,
    15 * 24 * 60 * 60,
    30 * 24 * 60 * 60,
    45 * 24 * 60 * 60,
    60 * 24 * 60 * 60,
]


@dataclass
class SearchEntry:
    word: str
    dictionary_code: str
    definitions: list[str]
    examples: list[str]
    meaning_examples: list[list[str]] = field(default_factory=list)
    raw_entry_id: str | None = None
    raw_entry_url: str | None = None


@dataclass
class ReviewHistoryItem:
    reviewed_at: str
    correct: bool
    chosen_answer: str
    correct_answer: str


@dataclass
class ReviewState:
    stage_index: int = 0
    next_review_at: str = field(
        default_factory=lambda: (
            datetime.now(UTC) + timedelta(seconds=DEFAULT_REVIEW_INTERVALS[0])
        ).isoformat()
    )
    last_reviewed_at: str | None = None
    history: list[ReviewHistoryItem] = field(default_factory=list)


@dataclass
class SavedWord:
    word: str
    added_at: str
    definitions: list[str]
    examples: list[str]
    source_dictionary_code: str
    source_entry_id: str | None
    source_entry_url: str | None
    review: ReviewState
