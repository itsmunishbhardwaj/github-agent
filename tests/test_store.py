from researcher.store import (
    blob_known, branch_delta, claims_by_id, load_claims, record_branch_file, record_head, save_claims,
)

from .conftest import make_claim, seed as index


def test_load_claims_returns_only_claims_reachable_from_the_branch(db):
    index(db, "alice", "a.md", "b1", [make_claim("m1", path="a.md")])
    index(db, "bob", "b.md", "b2", [make_claim("m2", path="b.md")])
    assert [c.id for c in load_claims(db, "alice")] == ["m1"]


def test_save_claims_twice_does_not_duplicate(db):
    save_claims(db, "b1", [make_claim("m1")])
    save_claims(db, "b1", [make_claim("m1")])
    assert db.execute("SELECT count(*) FROM claims").fetchone()[0] == 1


def test_blob_known_after_claims_saved_or_file_recorded(db):
    assert not blob_known(db, "b1")
    save_claims(db, "b1", [make_claim("m1")])
    assert blob_known(db, "b1")
    record_branch_file(db, "alice", "empty.md", "b9", "h")  # a blob that produced zero claims
    assert blob_known(db, "b9")


def test_claims_by_id_spans_all_branches(db):
    index(db, "alice", "a.md", "b1", [make_claim("m1")])
    index(db, "bob", "b.md", "b2", [make_claim("m2", path="b.md")])
    assert set(claims_by_id(db)) == {"m1", "m2"}


def test_branch_delta_is_added_and_removed_against_the_merge_base(db):
    index(db, "alice@base", "a.md", "b0", [make_claim("m0", "old finding")])
    index(db, "alice", "a.md", "b1", [make_claim("m1", "new finding")])
    record_head(db, "alice", "h1", "Alice")
    d = branch_delta(db, "alice")
    assert [c.id for c in d.added] == ["m1"]
    assert [c.id for c in d.removed] == ["m0"]


def test_branch_delta_ignores_claims_merged_to_main_after_the_fork(db):
    index(db, "alice@base", "a.md", "b0", [make_claim("m0")])
    index(db, "alice", "a.md", "b0", [make_claim("m0")])
    index(db, "main", "z.md", "bz", [make_claim("mz", path="z.md")])  # landed on main after alice forked
    record_head(db, "alice", "h1", "Alice")
    d = branch_delta(db, "alice")
    assert d.added == [] and d.removed == []


def test_branch_delta_treats_a_deleted_file_as_removed_claims(db):
    index(db, "alice@base", "a.md", "b0", [make_claim("m0")])
    record_head(db, "alice", "h1", "Alice")  # alice's tree no longer has a.md
    assert [c.id for c in branch_delta(db, "alice").removed] == ["m0"]


def test_branch_delta_reports_head_sha_and_author(db):
    record_head(db, "alice", "h1", "Alice")
    d = branch_delta(db, "alice")
    assert (d.branch, d.head_sha, d.author) == ("alice", "h1", "Alice")
