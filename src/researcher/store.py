import sqlite3
from pathlib import Path

from .models import BranchDelta, Claim

_COLS = "c.id, c.text, c.kind, c.source_path, c.line_start, c.line_end, c.commit_sha, c.author"


def open_db(root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(root / ".researcher" / "state.db")
    db.executescript((Path(__file__).parent / "schema.sql").read_text())
    return db


def _claim(r: tuple) -> Claim:
    return Claim(id=r[0], text=r[1], kind=r[2], source_path=r[3], line_start=r[4], line_end=r[5], commit=r[6], author=r[7])


def save_claims(db: sqlite3.Connection, blob_sha: str, claims: list[Claim]) -> None:
    db.executemany(
        "INSERT OR IGNORE INTO claims VALUES (?,?,?,?,?,?,?,?,?)",
        [(blob_sha, c.id, c.text, c.kind, c.source_path, c.line_start, c.line_end, c.commit, c.author) for c in claims],
    )
    db.commit()


def record_branch_file(db: sqlite3.Connection, branch: str, path: str, blob_sha: str, head_sha: str) -> None:
    db.execute("INSERT OR REPLACE INTO branch_files VALUES (?,?,?,?)", (branch, path, blob_sha, head_sha))
    db.commit()


def record_head(db: sqlite3.Connection, branch: str, head_sha: str, author: str) -> None:
    db.execute("INSERT OR REPLACE INTO seen_heads VALUES (?,?,?)", (branch, head_sha, author))
    db.commit()


def blob_known(db: sqlite3.Connection, blob_sha: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM claims WHERE blob_sha = :b UNION SELECT 1 FROM branch_files WHERE blob_sha = :b LIMIT 1",
        {"b": blob_sha},
    ).fetchone()
    return row is not None


def load_claims(db: sqlite3.Connection, branch: str) -> list[Claim]:
    rows = db.execute(
        f"SELECT DISTINCT {_COLS} FROM claims c JOIN branch_files b ON b.blob_sha = c.blob_sha WHERE b.branch = ?",
        (branch,),
    ).fetchall()
    return [_claim(r) for r in rows]


def claims_by_id(db: sqlite3.Connection) -> dict[str, Claim]:
    return {r[0]: _claim(r) for r in db.execute(f"SELECT {_COLS} FROM claims c").fetchall()}


def branch_delta(db: sqlite3.Connection, branch: str) -> BranchDelta:
    """Claims added/removed relative to the merge-base, indexed under `<branch>@base`."""
    base, now = load_claims(db, f"{branch}@base"), load_claims(db, branch)
    base_ids, now_ids = {c.id for c in base}, {c.id for c in now}
    head_sha, author = db.execute("SELECT head_sha, author FROM seen_heads WHERE branch = ?", (branch,)).fetchone()
    return BranchDelta(
        branch=branch, head_sha=head_sha, author=author,
        added=[c for c in now if c.id not in base_ids],
        removed=[c for c in base if c.id not in now_ids],
    )
