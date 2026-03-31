from __future__ import annotations

import html
import json
import os
import re
from html.parser import HTMLParser
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from vocab_shell.models import SearchEntry


class CollinsError(RuntimeError):
    pass


class _Capture:
    def __init__(self, target: str) -> None:
        self.target = target
        self.depth = 1
        self.buffer: list[str] = []


class _EntryContentParser(HTMLParser):
    TARGET_CLASS_FRAGMENTS = {
        "definitions": ("def", "type-def"),
        "examples": ("quote", "example", "type-example", "cit"),
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_stack: list[_Capture] = []
        self.definitions: list[str] = []
        self.examples: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for capture in self._capture_stack:
            capture.depth += 1
        attr_map = dict(attrs)
        class_name = (attr_map.get("class") or "").lower()
        target = self._match_target(class_name)
        if target:
            self._capture_stack.append(_Capture(target))
            return
        if self._capture_stack and tag in {"br", "p", "div", "li"}:
            self._capture_stack[-1].buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        completed: list[_Capture] = []
        for capture in self._capture_stack:
            capture.depth -= 1
        while self._capture_stack and self._capture_stack[-1].depth <= 0:
            completed.append(self._capture_stack.pop())
        for capture in completed:
            text = self._normalize_text("".join(capture.buffer))
            if text:
                getattr(self, capture.target).append(text)

    def handle_data(self, data: str) -> None:
        if self._capture_stack:
            self._capture_stack[-1].buffer.append(data)

    @classmethod
    def _match_target(cls, class_name: str) -> str | None:
        for target, fragments in cls.TARGET_CLASS_FRAGMENTS.items():
            if any(fragment in class_name for fragment in fragments):
                return target
        return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text


class CollinsClient:
    base_url = "https://www.collinsdictionary.com/dictionary"
    fallback_api_url = "https://api.dictionaryapi.dev/api/v2/entries/en"
    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, api_key: str | None = None, dictionary_code: str | None = None) -> None:
        self.dictionary_code = dictionary_code or os.getenv("COLLINS_DICT_CODE", "english")

    def search(self, word: str) -> SearchEntry:
        normalized_word = word.strip()
        if not normalized_word:
            raise CollinsError("Search word cannot be empty.")
        fallback = self._search_via_fallback_api(normalized_word)
        if fallback:
            return fallback

        path = quote(normalized_word.replace(" ", "-"), safe="-")
        url = f"{self.base_url}/{self.dictionary_code}/{path}"
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.collinsdictionary.com/",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                page_html = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code == 404:
                raise CollinsError(f"No definition found for '{word}'.") from exc
            if exc.code == 403:
                fallback = self._search_via_fallback_api(normalized_word)
                if fallback:
                    return fallback
                raise CollinsError(
                    "Collins blocked the request (HTTP 403) and fallback lookup failed. "
                    "Please try again later."
                ) from exc
            raise CollinsError(f"Collins page request failed: HTTP {exc.code}") from exc
        except URLError as exc:
            raise CollinsError(f"Could not reach Collins Dictionary: {exc.reason}") from exc

        definitions, meaning_examples = self._parse_entry_content(page_html)
        examples = [example for group in meaning_examples for example in group]

        if not definitions and not examples:
            plain = self._strip_html(page_html)
            if plain:
                definitions = [plain[:500]]

        if not definitions:
            raise CollinsError(f"No usable definition returned for '{word}'.")

        entry_word = self._extract_headword(page_html) or normalized_word
        canonical_url = self._extract_canonical_url(page_html) or url

        return SearchEntry(
            word=entry_word,
            dictionary_code=self.dictionary_code,
            definitions=definitions,
            examples=examples,
            meaning_examples=meaning_examples,
            raw_entry_id=None,
            raw_entry_url=canonical_url,
        )

    def _search_via_fallback_api(self, word: str) -> SearchEntry | None:
        url = f"{self.fallback_api_url}/{quote(word)}"
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except (HTTPError, URLError, json.JSONDecodeError):
            return None
        return self._search_entry_from_fallback_payload(payload, word)

    def _search_entry_from_fallback_payload(self, payload: object, fallback_word: str) -> SearchEntry | None:
        if not isinstance(payload, list) or not payload:
            return None
        entry = payload[0]
        if not isinstance(entry, dict):
            return None

        definitions: list[str] = []
        meaning_examples: list[list[str]] = []
        meanings = entry.get("meanings")
        if isinstance(meanings, list):
            for meaning in meanings:
                if not isinstance(meaning, dict):
                    continue
                part_of_speech = self._normalize_part_of_speech(str(meaning.get("partOfSpeech", "")))
                defs = meaning.get("definitions")
                if not isinstance(defs, list):
                    continue
                for item in defs:
                    if not isinstance(item, dict):
                        continue
                    definition = str(item.get("definition", "")).strip()
                    if definition:
                        definitions.append(definition)
                    examples_for_definition: list[str] = []
                    example = str(item.get("example", "")).strip()
                    if self._looks_like_example_sentence(example):
                        examples_for_definition.append(f"[{part_of_speech}] {example}")
                    meaning_examples.append(examples_for_definition)

        definitions, meaning_examples = self._dedupe_senses(definitions, meaning_examples)
        examples = [example for group in meaning_examples for example in group]

        if not definitions:
            return None

        source_urls = entry.get("sourceUrls")
        source_url = None
        if isinstance(source_urls, list) and source_urls:
            source_url = str(source_urls[0])

        return SearchEntry(
            word=str(entry.get("word") or fallback_word),
            dictionary_code=self.dictionary_code,
            definitions=definitions,
            examples=examples,
            meaning_examples=meaning_examples,
            raw_entry_id=None,
            raw_entry_url=source_url,
        )

    def _parse_entry_content(self, entry_content: str) -> tuple[list[str], list[list[str]]]:
        parser = _EntryContentParser()
        parser.feed(entry_content)
        definitions = self._clean_definitions(parser.definitions)
        examples = self._normalize_example_items(self._dedupe(parser.examples))
        meaning_examples = self._attach_examples_to_definitions(definitions, examples)
        return definitions, meaning_examples

    @classmethod
    def _clean_definitions(cls, items: Iterable[str]) -> list[str]:
        definitions = cls._dedupe(items)
        has_multi_word = any(len(re.findall(r"[A-Za-z]+", item)) >= 2 for item in definitions)
        cleaned: list[str] = []
        for item in definitions:
            if re.fullmatch(r"[\W_]*\d+[\W_]*", item):
                continue
            if re.fullmatch(r"[\W_]+", item):
                continue
            if has_multi_word:
                words = re.findall(r"[A-Za-z]+", item)
                if len(words) == 1 and words[0].islower():
                    continue
            cleaned.append(item)
        return cleaned

    @staticmethod
    def _normalize_part_of_speech(raw: str) -> str:
        text = raw.strip().upper()
        if not text:
            return "EXAMPLE"
        aliases = {
            "ADJ": "ADJECTIVE",
            "ADV": "ADVERB",
            "N": "NOUN",
            "V": "VERB",
        }
        return aliases.get(text, text)

    @classmethod
    def _normalize_example_items(cls, items: Iterable[str]) -> list[str]:
        results: list[str] = []
        pending_pos = "EXAMPLE"
        for item in items:
            marker = cls._extract_pos_marker(item)
            if marker:
                pending_pos = marker
                continue
            if not cls._looks_like_example_sentence(item):
                continue
            results.append(f"[{pending_pos}] {item}")
        return cls._dedupe(results)

    @staticmethod
    def _extract_pos_marker(text: str) -> str | None:
        match = re.fullmatch(r"\[\s*([A-Za-z-]+)(?:\s+[A-Za-z-]+)*\s*\]", text.strip())
        if not match:
            return None
        token = match.group(1).upper()
        token = token.split("-")[0]
        if token in {"NOUN", "VERB", "ADJECTIVE", "ADVERB", "PRONOUN", "PREPOSITION", "CONJUNCTION"}:
            return token
        return "EXAMPLE"

    @staticmethod
    def _looks_like_example_sentence(text: str) -> bool:
        if not text:
            return False
        if re.fullmatch(r"\[[^\]]+\]", text.strip()):
            return False
        words = re.findall(r"[A-Za-z]+", text)
        return len(words) >= 4

    @staticmethod
    def _attach_examples_to_definitions(definitions: list[str], examples: list[str]) -> list[list[str]]:
        groups = [[] for _ in definitions]
        if not definitions or not examples:
            return groups

        seed_count = min(len(definitions), len(examples))
        for idx in range(seed_count):
            groups[idx].append(examples[idx])
        for idx in range(seed_count, len(examples)):
            groups[idx % len(definitions)].append(examples[idx])
        return groups

    @classmethod
    def _dedupe_senses(
        cls, definitions: list[str], meaning_examples: list[list[str]]
    ) -> tuple[list[str], list[list[str]]]:
        seen: set[str] = set()
        out_definitions: list[str] = []
        out_examples: list[list[str]] = []
        for idx, definition in enumerate(definitions):
            key = re.sub(r"\s+", " ", definition).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out_definitions.append(definition)
            if idx < len(meaning_examples):
                out_examples.append(cls._dedupe(meaning_examples[idx]))
            else:
                out_examples.append([])
        return out_definitions, out_examples

    @staticmethod
    def _dedupe(items: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        results: list[str] = []
        for item in items:
            normalized = re.sub(r"\s+", " ", item).strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                results.append(normalized)
        return results

    @staticmethod
    def _strip_html(value: str) -> str:
        value = re.sub(r"<(script|style)\b.*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _extract_headword(page_html: str) -> str | None:
        patterns = [
            r'<meta\s+property="og:title"\s+content="([^"]+?)\s+definition',
            r'<h1[^>]*>(.*?)</h1>',
        ]
        for pattern in patterns:
            match = re.search(pattern, page_html, flags=re.IGNORECASE | re.DOTALL)
            if match:
                text = CollinsClient._strip_html(match.group(1))
                if text:
                    return text
        return None

    @staticmethod
    def _extract_canonical_url(page_html: str) -> str | None:
        match = re.search(
            r'<link\s+rel="canonical"\s+href="([^"]+)"',
            page_html,
            flags=re.IGNORECASE,
        )
        if match:
            return html.unescape(match.group(1))
        return None
