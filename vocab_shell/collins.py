from __future__ import annotations

import html
import os
import re
from html.parser import HTMLParser
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from vocab_shell.models import SearchEntry


class CollinsError(RuntimeError):
    pass


class _EntryContentParser(HTMLParser):
    TARGET_CLASS_FRAGMENTS = {
        "definitions": ("def", "type-def", "sense"),
        "examples": ("quote", "example", "type-example", "cit"),
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture_stack: list[str] = []
        self._buffer: list[str] = []
        self.definitions: list[str] = []
        self.examples: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        class_name = (attr_map.get("class") or "").lower()
        target = self._match_target(class_name)
        if target:
            self._capture_stack.append(target)
            self._buffer.append("")
        elif self._capture_stack and tag in {"br", "p", "div", "li"}:
            self._buffer[-1] += "\n"

    def handle_endtag(self, tag: str) -> None:
        if self._capture_stack and tag in {"span", "div", "p", "li"}:
            text = self._normalize_text(self._buffer.pop())
            target = self._capture_stack.pop()
            if text:
                getattr(self, target).append(text)

    def handle_data(self, data: str) -> None:
        if self._capture_stack:
            self._buffer[-1] += data

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
    base_url = "https://api.collinsdictionary.com/api/v1"

    def __init__(self, api_key: str | None = None, dictionary_code: str | None = None) -> None:
        self.api_key = api_key or os.getenv("COLLINS_API_KEY")
        self.dictionary_code = dictionary_code or os.getenv("COLLINS_DICT_CODE", "english")
        if not self.api_key:
            raise CollinsError("Set COLLINS_API_KEY before using the search command.")

    def search(self, word: str) -> SearchEntry:
        query = urlencode({"q": word, "format": "html"})
        url = f"{self.base_url}/dictionaries/{self.dictionary_code}/search/first?{query}"
        request = Request(url, headers={"accessKey": self.api_key, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise CollinsError(f"Collins API request failed: HTTP {exc.code} {detail}") from exc
        except URLError as exc:
            raise CollinsError(f"Could not reach Collins API: {exc.reason}") from exc

        import json

        data = json.loads(payload)
        entry_content = data.get("entryContent", "")
        definitions, examples = self._parse_entry_content(entry_content)

        if not definitions and not examples:
            plain = self._strip_html(entry_content)
            if plain:
                definitions = [plain[:500]]

        if not definitions:
            raise CollinsError(f"No usable definition returned for '{word}'.")

        return SearchEntry(
            word=data.get("entryLabel") or word,
            dictionary_code=data.get("dictionaryCode", self.dictionary_code),
            definitions=definitions[:5],
            examples=examples[:5],
            raw_entry_id=data.get("entryId"),
            raw_entry_url=data.get("entryUrl"),
        )

    def _parse_entry_content(self, entry_content: str) -> tuple[list[str], list[str]]:
        parser = _EntryContentParser()
        parser.feed(entry_content)
        definitions = self._dedupe(parser.definitions)
        examples = self._dedupe(parser.examples)
        return definitions, examples

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
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
        return re.sub(r"\s+", " ", value).strip()
