import unittest

from scripts.local_fm_code_review import ReviewError, build_prompt, parse_review_output


class LocalFmCodeReviewTests(unittest.TestCase):
    def test_accepts_valid_pass_without_findings(self):
        result = parse_review_output(
            '{"verdict":"PASS","summary":"No critical risks found.","findings":[]}'
        )
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["findings"], [])

    def test_rejects_pass_with_high_finding(self):
        raw = (
            '{"verdict":"PASS","summary":"Looks fine","findings":['
            '{"severity":"high","file":"app.py","issue":"unsafe","evidence":"line 2",'
            '"recommendation":"validate input"}]}'
        )
        with self.assertRaises(ReviewError):
            parse_review_output(raw)

    def test_rejects_missing_evidence(self):
        raw = (
            '{"verdict":"FAIL","summary":"Risk found","findings":['
            '{"severity":"high","file":"app.py","issue":"unsafe",'
            '"evidence":"","recommendation":"validate input"}]}'
        )
        with self.assertRaises(ReviewError):
            parse_review_output(raw)

    def test_accepts_fenced_json(self):
        raw = ' ```json\n{"verdict":"FAIL","summary":"Risk","findings":[]}\n``` '
        self.assertEqual(parse_review_output(raw)["verdict"], "FAIL")

    def test_prompt_treats_diff_as_untrusted_and_forbids_test_claims(self):
        prompt = build_prompt("print('hello')")
        self.assertIn("untrusted source data", prompt)
        self.assertIn("Do not claim tests were run", prompt)


if __name__ == "__main__":
    unittest.main()
