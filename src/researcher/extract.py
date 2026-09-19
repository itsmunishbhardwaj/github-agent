import hashlib
from pathlib import Path

import pathspec
from pydantic import BaseModel

from .llm import ask
from .models import Claim, ClaimKind

CLAIM_SYSTEM = (
    "Extract atomic, self-contained research claims (findings, hypotheses, methods, citations). "
    "Give the 1-based line range each comes from."
)


class _Extracted(BaseModel):
    text: str
    kind: ClaimKind
    line_start: int
    line_end: int


class _ExtractedClaims(BaseModel):
    claims: list[_Extracted]


def ignore_spec(root: Path) -> pathspec.PathSpec:
    f = root / ".researcherignore"
    return pathspec.PathSpec.from_lines("gitignore", f.read_text().splitlines() if f.exists() else [])


def claim_id(path: str, text: str) -> str:
    return hashlib.sha1(f"{path}:{text}".encode()).hexdigest()[:12]


def extract_claims(path: str, text: str, commit: str, author: str) -> list[Claim]:
    numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(text.splitlines(), 1))
    result = ask(CLAIM_SYSTEM, {"path": path, "text": numbered}, _ExtractedClaims)
    return [
        Claim(id=claim_id(path, c.text), source_path=path, commit=commit, author=author, **c.model_dump())
        for c in result.claims
    ]
