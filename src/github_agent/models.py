from typing import Literal

from pydantic import BaseModel, Field

ClaimKind = Literal["finding", "hypothesis", "method", "citation"]


class Claim(BaseModel):
    id: str  # sha1(source_path + text)[:12]
    text: str
    kind: ClaimKind
    source_path: str
    line_start: int
    line_end: int
    commit: str
    author: str


class BranchDelta(BaseModel):
    branch: str
    head_sha: str
    author: str
    added: list[Claim]
    removed: list[Claim]


class ReconcileInput(BaseModel):
    merged_kb: list[Claim]  # claims currently on main
    ours: BranchDelta  # branch the PR is opened from
    theirs: BranchDelta  # collaborator's unmerged branch
    candidate_pairs: list[tuple[str, str]] = Field(default_factory=list)  # FTS5 pre-pass: (our claim id, other claim id)


ConflictKind = Literal["contradiction", "duplicate", "supersedes", "needs_source"]
Severity = Literal["blocking", "review", "info"]


class Conflict(BaseModel):
    kind: ConflictKind
    severity: Severity
    claim_ids: list[str]
    explanation: str
    suggested_resolution: str


class PRDraft(BaseModel):
    title: str
    body_md: str
    consent_questions: list[str]  # what the collaborator is asked to agree to


class ReconcileOutput(BaseModel):
    conflicts: list[Conflict]
    recommendation: Literal["merge", "discuss", "hold"]
    pr: PRDraft
