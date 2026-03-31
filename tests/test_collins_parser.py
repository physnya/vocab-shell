from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from vocab_shell.collins import CollinsClient, CollinsError


class CollinsParserTests(unittest.TestCase):
    def test_parse_entry_content_extracts_definitions_and_examples(self) -> None:
        client = CollinsClient()
        html = """
        <div class="entry">
          <div class="def">to leave something behind permanently</div>
          <div class="quote">He had to abandon the plan after one week.</div>
        </div>
        """
        definitions, meaning_examples = client._parse_entry_content(html)
        self.assertEqual(definitions, ["to leave something behind permanently"])
        self.assertEqual(meaning_examples, [["[EXAMPLE] He had to abandon the plan after one week."]])

    def test_parse_entry_content_handles_nested_markup(self) -> None:
        client = CollinsClient()
        html = """
        <div class="content definitions">
          <span class="def">
            If you <span class="hi" rend="b">abandon</span> something, you stop doing it.
          </span>
          <div class="cit type-example">
            <span>He abandoned the trip after one week.</span>
          </div>
        </div>
        """
        definitions, meaning_examples = client._parse_entry_content(html)
        self.assertEqual(definitions, ["If you abandon something, you stop doing it."])
        self.assertEqual(meaning_examples, [["[EXAMPLE] He abandoned the trip after one week."]])

    def test_parse_entry_content_filters_number_only_and_single_word_noise(self) -> None:
        client = CollinsClient()
        html = """
        <div class="entry">
          <div class="def">1.</div>
          <div class="def">visits</div>
          <div class="def">You use to when indicating movement toward a place.</div>
          <div class="quote">She went to the window and looked out.</div>
        </div>
        """
        definitions, meaning_examples = client._parse_entry_content(html)
        self.assertEqual(definitions, ["You use to when indicating movement toward a place."])
        self.assertEqual(meaning_examples, [["[EXAMPLE] She went to the window and looked out."]])

    def test_extracts_headword_and_canonical_url_from_public_page(self) -> None:
        client = CollinsClient()
        page_html = """
        <html>
          <head>
            <meta property="og:title" content="abandon definition and meaning | Collins English Dictionary">
            <link rel="canonical" href="https://www.collinsdictionary.com/dictionary/english/abandon">
          </head>
          <body></body>
        </html>
        """
        self.assertEqual(client._extract_headword(page_html), "abandon")
        self.assertEqual(
            client._extract_canonical_url(page_html),
            "https://www.collinsdictionary.com/dictionary/english/abandon",
        )

    def test_builds_entry_from_fallback_api_payload(self) -> None:
        client = CollinsClient()
        payload = [
            {
                "word": "abandon",
                "meanings": [
                    {
                        "partOfSpeech": "verb",
                        "definitions": [
                            {
                                "definition": "to leave behind",
                                "example": "They had to abandon the car.",
                            },
                            {
                                "definition": "to stop supporting",
                            },
                        ]
                    }
                ],
                "sourceUrls": ["https://example.test/abandon"],
            }
        ]

        entry = client._search_entry_from_fallback_payload(payload, "abandon")
        assert entry is not None
        self.assertEqual(entry.word, "abandon")
        self.assertEqual(entry.definitions, ["to leave behind", "to stop supporting"])
        self.assertEqual(entry.examples, ["[VERB] They had to abandon the car."])
        self.assertEqual(entry.meaning_examples, [["[VERB] They had to abandon the car."], []])
        self.assertEqual(entry.raw_entry_url, "https://example.test/abandon")

    def test_search_prefers_fallback_api(self) -> None:
        client = CollinsClient()
        fallback_entry = client._search_entry_from_fallback_payload(
            [
                {
                    "word": "abandon",
                    "meanings": [{"partOfSpeech": "verb", "definitions": [{"definition": "to leave behind"}]}],
                }
            ],
            "abandon",
        )
        assert fallback_entry is not None

        with patch("vocab_shell.collins.urlopen") as mock_urlopen:
            with patch.object(client, "_search_via_fallback_api", return_value=fallback_entry):
                entry = client.search("abandon")

        self.assertEqual(entry.word, "abandon")
        self.assertEqual(entry.definitions, ["to leave behind"])
        mock_urlopen.assert_not_called()

    def test_fallback_keeps_all_meanings_without_truncation(self) -> None:
        client = CollinsClient()
        payload = [
            {
                "word": "abandon",
                "meanings": [
                    {
                        "partOfSpeech": "verb",
                        "definitions": [
                            {"definition": f"meaning {idx}", "example": f"Example sentence {idx} with words."}
                            for idx in range(1, 8)
                        ],
                    }
                ],
            }
        ]
        entry = client._search_entry_from_fallback_payload(payload, "abandon")
        assert entry is not None
        self.assertEqual(len(entry.definitions), 7)
        self.assertEqual(len(entry.meaning_examples), 7)
        self.assertEqual(len(entry.examples), 7)

    def test_search_raises_clear_error_when_403_and_fallback_fails(self) -> None:
        client = CollinsClient()
        with patch("vocab_shell.collins.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                url="https://www.collinsdictionary.com/dictionary/english/abandon",
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=None,
            )
            with patch.object(client, "_search_via_fallback_api", return_value=None):
                with self.assertRaises(CollinsError) as context:
                    client.search("abandon")

        self.assertIn("HTTP 403", str(context.exception))


if __name__ == "__main__":
    unittest.main()
