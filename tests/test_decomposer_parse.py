import unittest

from acp_funcforge.decomposer import FunctionalDecomposer


class DecomposerParseTests(unittest.TestCase):
    def test_parse_plain_json(self):
        data = FunctionalDecomposer._parse_json('{"assumptions":[],"modules":[],"functions":[],"data_flow":[],"risks":[]}')
        self.assertEqual(data["functions"], [])

    def test_parse_fenced_json(self):
        text = "```json\n{\"functions\":[{\"name\":\"f\",\"purpose\":\"p\",\"inputs\":[],\"outputs\":[],\"dependencies\":[],\"language_hints\":[]}],\"assumptions\":[],\"modules\":[],\"data_flow\":[],\"risks\":[]}\n```"
        data = FunctionalDecomposer._parse_json(text)
        self.assertEqual(data["functions"][0]["name"], "f")

    def test_parse_embedded_object(self):
        text = "prefix {\"functions\":[],\"assumptions\":[\"a\"],\"modules\":[],\"data_flow\":[],\"risks\":[]} suffix"
        data = FunctionalDecomposer._parse_json(text)
        self.assertEqual(data["assumptions"], ["a"])

    def test_normalize_func_defaults(self):
        n = FunctionalDecomposer._normalize_func({"name": "x"})
        self.assertEqual(n["inputs"], [])
        self.assertEqual(n["dependencies"], [])


if __name__ == "__main__":
    unittest.main()
