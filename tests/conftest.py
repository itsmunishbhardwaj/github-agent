from pathlib import Path

import git
import pytest

from researcher.models import Claim, Conflict, PRDraft, ReconcileOutput
from researcher.store import open_db, record_branch_file, record_head, save_claims

from .gitutil import commit_file, run


def make_claim(id: str, text: str = "a finding", path: str = "a.md", line: int = 1, author: str = "alice", commit: str = "c0ffee") -> Claim:
    return Claim(id=id, text=text, kind="finding", source_path=path, line_start=line, line_end=line, commit=commit, author=author)


@pytest.fixture
def db(tmp_path):
    (tmp_path / ".researcher").mkdir()
    return open_db(tmp_path)


def seed(db, branch: str, path: str, blob: str, claims: list[Claim], head: str = "h") -> None:
    save_claims(db, blob, claims)
    record_branch_file(db, branch, path, blob, head)
    if not branch.endswith("@base"):
        record_head(db, branch, head, "Someone")


@pytest.fixture
def research_repo(tmp_path) -> Path:
    """Clone with main, alice/research, bob/research all pushed to origin; alice/research checked out."""
    run(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(tmp_path / "origin.git"))
    work = tmp_path / "work"
    run(tmp_path, "git", "clone", "-q", str(tmp_path / "origin.git"), str(work))
    commit_file(work, ".gitignore", ".env\n.researcher/state.db\n", "gitignore", author="Carol")
    commit_file(work, "notes.md", "# Notes\nBaseline finding one.\n", "base", author="Carol")
    run(work, "git", "push", "-q", "-u", "origin", "main")
    run(work, "git", "checkout", "-q", "-b", "bob/research")
    commit_file(work, "b.md", "Bob: effect persists to 60C.\n", "bob result", author="Bob")
    run(work, "git", "push", "-q", "-u", "origin", "bob/research")
    run(work, "git", "checkout", "-q", "-b", "alice/research", "main")
    commit_file(work, "notes.md", "# Notes\nBaseline finding one.\nAlice: effect vanishes above 40C.\n", "alice result", author="Alice")
    run(work, "git", "push", "-q", "-u", "origin", "alice/research")
    return work


@pytest.fixture
def ctx(research_repo, db_at):
    from researcher.context import Config, Ctx

    return Ctx(
        repo=git.Repo(research_repo), gh=None, db=db_at(research_repo),
        cfg=Config(main="main", repo="o/r", members={"alice": "alice/research", "bob": "bob/research"}),
    )


@pytest.fixture
def db_at():
    def make(root: Path):
        (root / ".researcher").mkdir(exist_ok=True)
        return open_db(root)
    return make


def make_output(conflicts=(), recommendation="discuss", title="add results") -> ReconcileOutput:
    return ReconcileOutput(
        conflicts=list(conflicts), recommendation=recommendation,
        pr=PRDraft(title=title, body_md="body", consent_questions=["ok?"]),
    )


def make_conflict(ids, kind="contradiction", severity="blocking") -> Conflict:
    return Conflict(kind=kind, severity=severity, claim_ids=list(ids), explanation="they disagree", suggested_resolution="rerun")
