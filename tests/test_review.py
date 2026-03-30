from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from vocab_shell.models import ReviewState, SavedWord
from vocab_shell.review import ReviewManager
from vocab_shell.storage import Storage


class ReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.tempdir.name))
        self.storage.create_dictionary("toefl")
        now = datetime.now(UTC) - timedelta(minutes=10)
        for word in ["abandon", "compile", "derive", "finite"]:
            self.storage.add_word(
                "toefl",
                SavedWord(
                    word=word,
                    added_at=datetime.now(UTC).isoformat(),
                    definitions=[f"definition for {word}"],
                    examples=[f"We should {word} the draft before class."],
                    source_dictionary_code="english",
                    source_entry_id=None,
                    source_entry_url=None,
                    review=ReviewState(next_review_at=now.isoformat()),
                ),
            )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_due_words_uses_schedule(self) -> None:
        manager = ReviewManager(self.storage)
        due = manager.due_words("toefl")
        self.assertEqual(len(due), 4)


if __name__ == "__main__":
    unittest.main()
