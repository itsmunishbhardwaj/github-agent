import pytest

from researcher import index as index_mod
from researcher.models import Claim
from researcher.store import branch_delta, load_claims

from .gitutil import commit_file

BRANCHES = ["alice/research", "main", "bob/research"]


@pytest.fixture
def extracted(monkeypatch):
    """Fake the LLM claim extractor: one claim per non-heading line, deliberately mis-attributed."""
    calls = []

    def fake(path, text, commit, author):
        calls.append(path)
        return [
            Claim(id=f"{path}:{i}", text=line, kind="finding", source_path=path, line_start=i, line_end=i, commit="?", author="?")
            for i, line in enumerate(text.splitlines(), 1) if line and not line.startswith("#")
        ]

    monkeypatch.setattr(index_mod, "extract_claims", fake)
    return calls


def test_indexes_each_branch_tip_and_records_head_and_author(ctx, extracted):
    index_mod.index_branches(ctx, BRANCHES)
    assert {c.text for c in load_claims(ctx.db, "alice/research")} == {"Baseline finding one.", "Alice: effect vanishes above 40C."}
    assert {c.text for c in load_claims(ctx.db, "bob/research")} >= {"Bob: effect persists to 60C."}
    d = branch_delta(ctx.db, "bob/research")
    assert d.author == "Bob" and len(d.head_sha) == 40


def test_claims_are_attributed_by_git_blame_not_by_the_tip_commit(ctx, extracted):
    index_mod.index_branches(ctx, BRANCHES)
    by_text = {c.text: c for c in load_claims(ctx.db, "alice/research")}
    assert by_text["Baseline finding one."].author == "Carol"
    assert by_text["Alice: effect vanishes above 40C."].author == "Alice"
    assert len(by_text["Alice: effect vanishes above 40C."].commit) == 8


def test_the_delta_is_only_what_the_branch_added_since_the_fork(ctx, extracted):
    index_mod.index_branches(ctx, BRANCHES)
    assert [c.text for c in branch_delta(ctx.db, "alice/research").added] == ["Alice: effect vanishes above 40C."]
    assert [c.text for c in branch_delta(ctx.db, "bob/research").added] == ["Bob: effect persists to 60C."]


def test_a_rerun_does_not_reextract_known_blobs(ctx, extracted):
    index_mod.index_branches(ctx, BRANCHES)
    n = len(extracted)
    index_mod.index_branches(ctx, BRANCHES)
    assert len(extracted) == n


def test_ignored_files_and_researcher_internals_are_never_extracted(ctx, extracted, research_repo):
    commit_file(research_repo, ".researcherignore", "private/\n", "ignore")
    commit_file(research_repo, "private/secret.md", "top secret\n", "secret")
    commit_file(research_repo, "data.csv", "a,b\n", "data")
    commit_file(research_repo, ".researcher/config.toml", 'main = "main"\n', "cfg")
    index_mod.index_branches(ctx, ["alice/research"])
    assert set(extracted) == {"notes.md"}


def test_a_binary_doc_is_indexed_through_its_committed_sidecar(ctx, extracted, research_repo):
    commit_file(research_repo, "paper.pdf", b"%PDF", "add paper")
    commit_file(research_repo, ".researcher/text/paper.pdf.md", "Paper says X.\n", "extract", author="Bob")
    index_mod.index_branches(ctx, ["alice/research"])
    c = next(c for c in load_claims(ctx.db, "alice/research") if c.text == "Paper says X.")
    assert (c.source_path, c.author) == ("paper.pdf", "Bob")


def test_a_claim_with_an_out_of_range_line_falls_back_to_the_tip_commit(ctx, monkeypatch):
    def invented_line(path, text, commit, author):  # like the real extractor: tip commit/author unless index overrides
        return [Claim(id="x", text="invented line", kind="finding", source_path=path, line_start=99, line_end=99, commit=commit, author=author)]

    monkeypatch.setattr(index_mod, "extract_claims", invented_line)
    index_mod.index_branches(ctx, ["alice/research"])
    c = load_claims(ctx.db, "alice/research")[0]
    assert c.author == "Alice" and c.commit == ctx.repo.commit("alice/research").hexsha[:8]
