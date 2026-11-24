import git
from pydantic import BaseModel

TEXT_SUFFIXES = (".md", ".txt", ".mmd", ".mermaid")


class BlameLine(BaseModel):
    line: int
    sha: str
    author: str
    text: str


def sidecar_for(path: str) -> str:
    """Blame and claims run on text. Binary docs are handled through their committed extracted-markdown sidecar."""
    return path if path.endswith(TEXT_SUFFIXES) else f".github-agent/text/{path}.md"


def blame_lines(repo: git.Repo, path: str, rev: str = "HEAD") -> list[BlameLine]:
    out, n = [], 1
    for commit, lines in repo.blame(rev, sidecar_for(path)):
        for text in lines:
            out.append(BlameLine(line=n, sha=commit.hexsha[:8], author=commit.author.name, text=text))
            n += 1
    return out


def file_history(repo: git.Repo, path: str) -> list[tuple[str, str, str, str]]:
    return [
        (c.hexsha[:8], c.author.name, c.committed_datetime.date().isoformat(), c.summary)
        for c in repo.iter_commits(paths=[path, sidecar_for(path)])
    ]


def revert_commit(repo: git.Repo, sha: str) -> str:
    try:
        repo.git.revert(sha, "--no-edit")
    except git.GitCommandError:
        repo.git.revert("--abort")
        raise
    return f"reverted {sha[:8]} as {repo.head.commit.hexsha[:8]}"


def dirty_paths(repo: git.Repo) -> list[str]:
    return [d.a_path for d in repo.index.diff(None)] + list(repo.untracked_files)
