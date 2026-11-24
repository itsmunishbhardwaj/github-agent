from typing import Literal

from pydantic import BaseModel

ActionKind = Literal[
    "fetch", "extract", "reconcile", "commit", "pull_rebase",
    "push", "open_pr", "comment_pr", "set_status", "merge_pr", "revert",
]


class Action(BaseModel):
    kind: ActionKind
    detail: str  # commit message, sha, comment text, or shell fragment depending on kind
    reason: str


OWN_BRANCH_AUTO: frozenset[str] = frozenset({"fetch", "extract", "reconcile", "commit", "pull_rebase"})
PROTECTED = frozenset({"main"})


def decide(action: Action, current_branch: str) -> Literal["auto", "ask", "deny"]:
    if "force" in action.detail.lower():
        return "deny"
    if action.kind in OWN_BRANCH_AUTO:
        return "deny" if current_branch in PROTECTED else "auto"
    return "ask"
