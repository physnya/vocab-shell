from __future__ import annotations

import os
import unittest

from vocab_shell.collins import CollinsClient


class CollinsParserTests(unittest.TestCase):
    def test_parse_entry_content_extracts_definitions_and_examples(self) -> None:
        os.environ["COLLINS_API_KEY"] = "dummy"
        client = CollinsClient()
        html = """
        <div class="entry">
          <div class="def">to leave something behind permanently</div>
          <div class="quote">He had to abandon the plan after one week.</div>
        </div>
        """
        definitions, examples = client._parse_entry_content(html)
        self.assertEqual(definitions, ["to leave something behind permanently"])
        self.assertEqual(examples, ["He had to abandon the plan after one week."])


if __name__ == "__main__":
    unittest.main()
