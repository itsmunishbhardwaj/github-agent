import re
import sqlite3

from .llm import MODEL, get_client
from .models import Claim, ReconcileInput, ReconcileOutput
from .store import branch_delta, load_claims

SYSTEM = """You review two collaborators' unmerged research branches against the merged knowledge base on main.
`ours.added/removed` and `theirs.added/removed` are claims added or removed since each branch forked from main.
Report only real conflicts between claims: contradictions, duplicates, supersession, missing sources.
Cite claim ids exactly as given; prefer pairs listed in candidate_pairs but you may cite others.
Severity blocking = the two claims cannot both be true. Then draft a pull request from `ours` into main
whose consent_questions ask the collaborator to agree to specific points. Title under 70 characters.
Recommendation is advice only; a human decides."""


class ReconcileError(Exception):
    pass


def _problems(inp: ReconcileInput, out: ReconcileOutput) -> list[str]:
    known = {c.id for c in (*inp.merged_kb, *inp.ours.added, *inp.ours.removed, *inp.theirs.added, *inp.theirs.removed)}
    problems = [f"unknown claim id {i}" for c in out.conflicts for i in c.claim_ids if i not in known]
    problems += [
        f"conflict needs 2+ claim ids: {c.explanation[:40]!r}"
        for c in out.conflicts
        if c.kind != "needs_source" and len(set(c.claim_ids)) < 2
    ]
    if len(out.pr.title) > 70:
        problems.append("pr.title over 70 chars")
    if out.recommendation == "merge" and any(c.severity == "blocking" for c in out.conflicts):
        problems.append("recommendation=merge while a blocking conflict exists")
    return problems


def reconcile_branches(inp: ReconcileInput, max_attempts: int = 3) -> ReconcileOutput:
    messages = [{"role": "user", "content": inp.model_dump_json()}]
    problems: list[str] = []
    for _ in range(max_attempts):
        resp = get_client().messages.parse(
            model=MODEL, max_tokens=16000, system=SYSTEM, messages=messages, output_format=ReconcileOutput
        )
        out = resp.parsed_output
        problems = _problems(inp, out)
        if not problems:
            return out
        text = next(b.text for b in resp.content if b.type == "text")
        messages = [*messages, {"role": "assistant", "content": text},
                    {"role": "user", "content": "Fix and resend: " + "; ".join(problems)}]
    raise ReconcileError(f"still invalid after {max_attempts} attempts: {problems}")


def candidate_pairs(db: sqlite3.Connection, ours: list[Claim], others: list[Claim], k: int = 5) -> list[tuple[str, str]]:
    other_ids = {c.id for c in others}
    pairs: list[tuple[str, str]] = []
    for c in ours:
        tokens = list(dict.fromkeys(re.findall(r"[a-z0-9]{4,}", c.text.lower())))[:12]
        if not tokens:
            continue
        rows = db.execute(
            "SELECT DISTINCT c.id FROM claims_fts JOIN claims c ON c.rowid = claims_fts.rowid "
            "WHERE claims_fts MATCH ? ORDER BY rank LIMIT ?",
            (" OR ".join(f'"{t}"' for t in tokens), k * 3),
        ).fetchall()
        pairs += [(c.id, r[0]) for r in rows if r[0] in other_ids and r[0] != c.id][:k]
    return pairs


def build_input(db: sqlite3.Connection, main: str, ours: str, theirs: str) -> ReconcileInput:
    merged = load_claims(db, main)
    o, t = branch_delta(db, ours), branch_delta(db, theirs)
    return ReconcileInput(
        merged_kb=merged, ours=o, theirs=t, candidate_pairs=candidate_pairs(db, o.added, [*t.added, *merged])
    )
