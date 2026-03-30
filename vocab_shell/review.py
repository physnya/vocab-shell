from __future__ import annotations

import random
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from vocab_shell.models import DEFAULT_REVIEW_INTERVALS, ReviewHistoryItem, SavedWord
from vocab_shell.storage import Storage


class ReviewError(RuntimeError):
    pass


class ReviewManager:
    def __init__(self, storage: Storage, rng: random.Random | None = None) -> None:
        self.storage = storage
        self.rng = rng or random.Random()

    def due_words(self, dictionary_name: str) -> list[SavedWord]:
        data = self.storage.load_dictionary(dictionary_name)
        now = datetime.now(UTC)
        due = []
        for payload in data.get("words", {}).values():
            word = self.storage.hydrate_saved_word(payload)
            if datetime.fromisoformat(word.review.next_review_at) <= now:
                due.append(word)
        self.rng.shuffle(due)
        return due

    def run_session(self, dictionary_name: str, requested_count: int) -> dict:
        data = self.storage.load_dictionary(dictionary_name)
        words = [self.storage.hydrate_saved_word(item) for item in data.get("words", {}).values()]
        if len(words) < 4:
            raise ReviewError("At least 4 saved words are required in a dictionary to run review.")

        due = [word for word in words if datetime.fromisoformat(word.review.next_review_at) <= datetime.now(UTC)]
        if not due:
            raise ReviewError("No words are due for review right now.")

        self.rng.shuffle(due)
        selected = due[:requested_count]
        if not selected:
            raise ReviewError("No words available for this review request.")

        correct_count = 0
        print(f"Starting review for '{dictionary_name}' with {len(selected)} question(s).")
        print("Type A, B, C, or D and press Enter.\n")

        index_map = {word.word.lower(): word for word in words}
        for idx, word in enumerate(selected, start=1):
            question = self._build_question(word, words)
            print(f"Question {idx}/{len(selected)}")
            print(question["prompt"])
            for label, choice in question["choices"]:
                print(f"  {label}. {choice}")
            answer = self._read_answer()
            chosen_word = question["answer_map"][answer]
            correct = chosen_word.lower() == word.word.lower()
            self._update_review_state(index_map[word.word.lower()], correct, chosen_word)
            if correct:
                correct_count += 1
                print("Correct.\n")
            else:
                print(f"Wrong. Correct answer: {question['correct_label']}. {word.word}\n")

        data["words"] = {word.word.lower(): asdict(word) for word in index_map.values()}
        self.storage.save_dictionary(dictionary_name, data)
        return {"total": len(selected), "correct": correct_count}

    def _build_question(self, word: SavedWord, pool: list[SavedWord]) -> dict:
        distractors = [item.word for item in pool if item.word.lower() != word.word.lower()]
        self.rng.shuffle(distractors)
        options = distractors[:3] + [word.word]
        self.rng.shuffle(options)
        labels = ["A", "B", "C", "D"]
        choice_pairs = list(zip(labels, options))
        sentence = self._choose_example(word)
        prompt = self._mask_word(sentence, word.word)
        answer_map = {label: value for label, value in choice_pairs}
        correct_label = next(label for label, value in choice_pairs if value.lower() == word.word.lower())
        return {
            "prompt": prompt,
            "choices": choice_pairs,
            "answer_map": answer_map,
            "correct_label": correct_label,
        }

    def _choose_example(self, word: SavedWord) -> str:
        for example in word.examples:
            if re.search(rf"\b{re.escape(word.word)}\b", example, flags=re.IGNORECASE):
                return example
        if word.examples:
            return word.examples[0]
        return f"Choose the best word for this definition: {word.definitions[0]}"

    @staticmethod
    def _mask_word(sentence: str, word: str) -> str:
        pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
        masked = pattern.sub("____", sentence)
        return masked if masked != sentence else sentence

    @staticmethod
    def _read_answer() -> str:
        while True:
            answer = input("Your answer: ").strip().upper()
            if answer in {"A", "B", "C", "D"}:
                return answer
            print("Please type A, B, C, or D.")

    @staticmethod
    def _update_review_state(word: SavedWord, correct: bool, chosen_answer: str) -> None:
        now = datetime.now(UTC)
        if correct:
            next_stage = min(word.review.stage_index + 1, len(DEFAULT_REVIEW_INTERVALS) - 1)
        else:
            next_stage = 0
        interval_seconds = DEFAULT_REVIEW_INTERVALS[next_stage]
        word.review.stage_index = next_stage
        word.review.last_reviewed_at = now.isoformat()
        word.review.next_review_at = (now + timedelta(seconds=interval_seconds)).isoformat()
        word.review.history.append(
            ReviewHistoryItem(
                reviewed_at=now.isoformat(),
                correct=correct,
                chosen_answer=chosen_answer,
                correct_answer=word.word,
            )
        )
