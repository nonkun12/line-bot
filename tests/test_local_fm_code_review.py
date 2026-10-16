import pytest

from scripts.local_fm_code_review import ReviewError, parse_review_output


def test_parses_valid_minimal_review():
    result = parse_review_output(
        '{"verdict":"PASS","summary":"No critical or high risks found","findings":[]}'
    )
    assert result["verdict"] == "PASS"
    assert result["findings"] == []


@pytest.mark.parametrize("raw", [
    "not json",
    "[]",
    '{"verdict":[],"summary":"x","findings":[]}',
    '{"verdict":"PASS","summary":"x","findings":[{"severity":[],"file":"x.py","issue":"x","evidence":"x","recommendation":"x"}]}',
    '{"verdict":"PASS","summary":"x","findings":[{"severity":"high","file":"x.py","issue":"x","evidence":"x","recommendation":"x"}]}',
])
def test_rejects_malformed_or_conflicting_review(raw):
    with pytest.raises(ReviewError):
        parse_review_output(raw)



def test_rejects_summary_over_bridge_limit():
    raw = '{"verdict":"PASS","summary":"' + ("x" * 4001) + '","findings":[]}'
    with pytest.raises(ReviewError, match="summary exceeds"):
        parse_review_output(raw)


def test_rejects_too_many_findings():
    finding = {"severity":"low","file":"x.py","issue":"x","evidence":"x","recommendation":"x"}
    raw = __import__("json").dumps({"verdict":"FAIL","summary":"reviewed","findings":[finding] * 101})
    with pytest.raises(ReviewError, match="maximum count"):
        parse_review_output(raw)


def test_rejects_finding_field_over_bridge_limit():
    finding = {"severity":"low","file":"x.py","issue":"x","evidence":"x" * 4001,"recommendation":"x"}
    raw = __import__("json").dumps({"verdict":"FAIL","summary":"reviewed","findings":[finding]})
    with pytest.raises(ReviewError, match="maximum length"):
        parse_review_output(raw)
