import os
import subprocess
from typing import Literal

from github import Auth, Github
from pydantic import BaseModel

from .models import PRDraft

CONTEXT = "github-agent/consent"


class PRComment(BaseModel):
    author: str
    body: str
    created_at: str


class PRState(BaseModel):
    number: int
    url: str
    consent: Literal["approved", "changes_requested", "pending"]
    new_comments: list[PRComment] = []  # filled in by sense(), not by pr_for_branch (which has no db access)


def github_token() -> str:
    if tok := os.environ.get("GITHUB_TOKEN"):
        return tok
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


class GitHubClient:
    def __init__(self, repo):
        self.repo = repo

    @classmethod
    def connect(cls, full_name: str, token: str | None = None) -> "GitHubClient":
        return cls(Github(auth=Auth.Token(token or github_token())).get_repo(full_name))

    def pr_for_branch(self, branch: str) -> PRState | None:
        prs = list(self.repo.get_pulls(state="open", head=f"{self.repo.owner.login}:{branch}"))
        if not prs:
            return None
        pr = prs[0]
        latest: dict[str, str] = {}
        for r in pr.get_reviews():  # chronological, so a reviewer's later review overwrites their earlier one
            if r.user.login != pr.user.login and r.state in {"APPROVED", "CHANGES_REQUESTED"}:
                latest[r.user.login] = r.state
        states = set(latest.values())
        consent = "changes_requested" if "CHANGES_REQUESTED" in states else "approved" if "APPROVED" in states else "pending"
        return PRState(number=pr.number, url=pr.html_url, consent=consent)

    def pr_comments(self, number: int, since: str | None = None) -> list[PRComment]:
        """The collaborator's plain PR comments (never the PR author's own), oldest first, optionally after `since`."""
        pr = self.repo.get_pull(number)
        out = [
            PRComment(author=c.user.login, body=c.body, created_at=c.created_at.isoformat())
            for c in pr.get_issue_comments()
            if c.user.login != pr.user.login
        ]
        out.sort(key=lambda c: c.created_at)
        return [c for c in out if since is None or c.created_at > since]

    def open_pr(self, head: str, base: str, draft: PRDraft) -> int:
        body = draft.body_md + "\n\n## Consent requested\n" + "\n".join(f"- [ ] {q}" for q in draft.consent_questions)
        return self.repo.create_pull(title=draft.title, body=body, head=head, base=base).number

    def comment(self, number: int, body: str) -> None:
        self.repo.get_pull(number).create_issue_comment(body)

    def set_status(self, sha: str, state: Literal["pending", "success", "failure"], description: str) -> None:
        self.repo.get_commit(sha).create_status(state=state, description=description[:140], context=CONTEXT)

    def merge(self, number: int) -> None:
        self.repo.get_pull(number).merge(merge_method="merge")  # merge commit keeps per-author history and blame
