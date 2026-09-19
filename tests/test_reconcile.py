import pytest

from researcher import reconcile as rc
from researcher.models import BranchDelta, Conflict, PRDraft, ReconcileInput, ReconcileOutput

from .conftest import make_claim, seed
from .fakes import FakeClaude


def out(conflicts=(), recommendation="discuss", title="add results"):
    return ReconcileOutput(
        conflicts=list(conflicts), recommendation=recommendation,
        pr=PRDraft(title=title, body_md="body", consent_questions=["ok?"]),
    )


def conflict(ids, kind="contradiction", severity="blocking"):
    return Conflict(kind=kind, severity=severity, claim_ids=list(ids), explanation="they disagree", suggested_resolution="rerun")


def inp():
    ours = BranchDelta(branch="alice", head_sha="h1", author="Alice", added=[make_claim("m1", "effect vanishes above 40C")], removed=[])
    theirs = BranchDelta(branch="bob", head_sha="h2", author="Bob", added=[make_claim("m2", "effect persists to 60C", author="bob")], removed=[])
    return ReconcileInput(merged_kb=[make_claim("m0", "baseline")], ours=ours, theirs=theirs, candidate_pairs=[("m1", "m2")])


@pytest.fixture
def fake(monkeypatch):
    def install(*outputs):
        f = FakeClaude(*outputs)
        monkeypatch.setattr(rc, "get_client", lambda: f)
        return f
    return install


def test_returns_the_model_output_when_it_validates(fake):
    good = out([conflict(["m1", "m2"])])
    f = fake(good)
    assert rc.reconcile_branches(inp()) == good
    assert len(f.calls) == 1


def test_sends_the_full_input_including_candidate_pairs(fake):
    f = fake(out())
    rc.reconcile_branches(inp())
    sent = f.calls[0]["messages"][0]["content"]
    assert "m1" in sent and "m2" in sent and "candidate_pairs" in sent
    assert f.calls[0]["output_format"] is ReconcileOutput


def test_retries_with_the_problem_named_when_a_claim_id_is_invented(fake):
    good = out([conflict(["m1", "m2"])])
    f = fake(out([conflict(["m1", "ghost"])]), good)
    assert rc.reconcile_branches(inp()) == good
    assert len(f.calls) == 2
    assert "unknown claim id ghost" in f.calls[1]["messages"][-1]["content"]


def test_rejects_a_merge_recommendation_while_a_blocking_conflict_exists(fake):
    f = fake(out([conflict(["m1", "m2"])], recommendation="merge"), out([conflict(["m1", "m2"])]))
    result = rc.reconcile_branches(inp())
    assert result.recommendation == "discuss"
    assert "recommendation=merge" in f.calls[1]["messages"][-1]["content"]


def test_rejects_a_pr_title_over_70_chars(fake):
    f = fake(out(title="x" * 71), out())
    assert rc.reconcile_branches(inp()).pr.title == "add results"
    assert "title over 70" in f.calls[1]["messages"][-1]["content"]


def test_a_two_sided_conflict_needs_two_distinct_claims(fake):
    f = fake(out([conflict(["m1", "m1"])]), out())
    rc.reconcile_branches(inp())
    assert "2+ claim ids" in f.calls[1]["messages"][-1]["content"]


def test_needs_source_may_cite_a_single_claim(fake):
    ok = out([conflict(["m1"], kind="needs_source", severity="review")])
    f = fake(ok)
    assert rc.reconcile_branches(inp()) == ok
    assert len(f.calls) == 1


def test_gives_up_with_reconcile_error_after_max_attempts(fake):
    bad = out([conflict(["m1", "ghost"])])
    f = fake(bad, bad, bad)
    with pytest.raises(rc.ReconcileError, match="ghost"):
        rc.reconcile_branches(inp(), max_attempts=3)
    assert len(f.calls) == 3


def test_candidate_pairs_link_related_claims_across_branches(db):
    ours = [make_claim("m1", "Thermal assay effect vanishes above 40C")]
    theirs = [make_claim("m2", "Thermal assay effect persists up to 60C"), make_claim("m3", "Unrelated pipetting technique note")]
    for i, c in enumerate([*ours, *theirs]):
        seed(db, "x", f"f{i}.md", f"b{i}", [c])
    pairs = rc.candidate_pairs(db, ours, theirs)
    assert ("m1", "m2") in pairs
    assert ("m1", "m3") not in pairs


def test_candidate_pairs_skip_a_claim_paired_with_itself(db):
    c = make_claim("m1", "Thermal assay effect vanishes above 40C")
    seed(db, "x", "a.md", "b1", [c])
    assert rc.candidate_pairs(db, [c], [c]) == []


def test_build_input_assembles_main_and_both_branch_deltas(db):
    seed(db, "main", "notes.md", "bm", [make_claim("m0", "baseline finding about the assay")])
    seed(db, "alice@base", "notes.md", "bm", [make_claim("m0", "baseline finding about the assay")])
    seed(db, "alice", "notes.md", "ba", [make_claim("m0", "baseline finding about the assay"), make_claim("m1", "Thermal assay effect vanishes above 40C")], head="h1")
    seed(db, "bob@base", "notes.md", "bm", [make_claim("m0", "baseline finding about the assay")])
    seed(db, "bob", "notes.md", "bb", [make_claim("m0", "baseline finding about the assay"), make_claim("m2", "Thermal assay effect persists up to 60C", author="bob")], head="h2")
    result = rc.build_input(db, main="main", ours="alice", theirs="bob")
    assert [c.id for c in result.merged_kb] == ["m0"]
    assert [c.id for c in result.ours.added] == ["m1"]
    assert [c.id for c in result.theirs.added] == ["m2"]
    assert ("m1", "m2") in result.candidate_pairs
