from researcher import extract
from researcher.extract import _Extracted, _ExtractedClaims


def test_ignore_spec_matches_gitignore_style_patterns(tmp_path):
    (tmp_path / ".researcherignore").write_text("private/\n*.secret.md\n")
    spec = extract.ignore_spec(tmp_path)
    assert spec.match_file("private/a.md") and spec.match_file("x.secret.md") and not spec.match_file("notes.md")


def test_ignore_spec_without_a_file_matches_nothing(tmp_path):
    assert not extract.ignore_spec(tmp_path).match_file("anything.md")


def test_claim_id_is_stable_and_depends_on_path_and_text():
    a = extract.claim_id("a.md", "x")
    assert a == extract.claim_id("a.md", "x") and len(a) == 12
    assert a != extract.claim_id("b.md", "x") and a != extract.claim_id("a.md", "y")


def test_extract_claims_numbers_the_lines_and_builds_claims(monkeypatch):
    seen = {}

    def fake_ask(system, payload, schema):
        seen["payload"] = payload
        return _ExtractedClaims(claims=[_Extracted(text="Effect vanishes above 40C", kind="finding", line_start=2, line_end=2)])

    monkeypatch.setattr(extract, "ask", fake_ask)
    claims = extract.extract_claims("notes.md", "# Notes\nEffect vanishes above 40C\n", "abc123", "Alice")
    assert seen["payload"]["text"] == "1: # Notes\n2: Effect vanishes above 40C"
    assert [(c.source_path, c.text, c.line_start, c.commit, c.author) for c in claims] == [
        ("notes.md", "Effect vanishes above 40C", 2, "abc123", "Alice")
    ]
    assert claims[0].id == extract.claim_id("notes.md", "Effect vanishes above 40C")
