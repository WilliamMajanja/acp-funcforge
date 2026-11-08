import unittest

from acp_funcforge.acp_client import ACPClient


class ACPExtractTests(unittest.TestCase):
    def test_extract_string_content(self):
        self.assertEqual(ACPClient._extract_text({"params": {"text": "hello"}}), "hello")
        self.assertEqual(ACPClient._extract_text({"params": {"update": {"text": "hi"}}}), "hi")

    def test_extract_content_blocks(self):
        msg = {"params": {"content": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]}}
        self.assertEqual(ACPClient._extract_text(msg), "AB")


if __name__ == "__main__":
    unittest.main()
