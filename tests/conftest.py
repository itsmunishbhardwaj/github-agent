import pytest

from researcher.models import Claim
from researcher.store import open_db, record_branch_file, record_head, save_claims


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
