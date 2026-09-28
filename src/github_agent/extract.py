import hashlib
from pathlib import Path

import pathspec
from pydantic import BaseModel

from .gitops import TEXT_SUFFIXES
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
    f = root / ".github-agentignore"
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


def extract_text(path: Path) -> str:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return path.read_text()
    raise ValueError(f"unsupported file type: {path.name}")


def write_sidecar(root: Path, src: Path) -> Path:
    out = root / ".github-agent" / "text" / (src.relative_to(root).as_posix() + ".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(extract_text(src))
    return out


def write_sidecars(root: Path) -> list[str]:
    """Writes a committed markdown sidecar for every non-text, non-ignored file that needs one."""
    spec = ignore_spec(root)
    written = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(part.startswith(".") for part in p.relative_to(root).parts) or spec.match_file(rel) or p.suffix.lower() in TEXT_SUFFIXES:
            continue  # dotfiles/dirs are config (.env, .git/, .github-agent/, .github-agentignore, ...), never content
        written.append(write_sidecar(root, p).as_posix())
    return written
