import pytest

from github_agent.policy import Action, decide


@pytest.mark.parametrize("kind,detail,branch,want", [
    ("fetch", "", "alice/research", "auto"),
    ("extract", "", "alice/research", "auto"),
    ("reconcile", "", "alice/research", "auto"),
    ("commit", "add finding", "alice/research", "auto"),
    ("pull_rebase", "", "alice/research", "auto"),
    ("fetch", "", "main", "deny"),
    ("commit", "x", "main", "deny"),
    ("push", "", "alice/research", "ask"),
    ("open_pr", "", "alice/research", "ask"),
    ("comment_pr", "hi", "alice/research", "ask"),
    ("set_status", "x", "alice/research", "ask"),
    ("merge_pr", "", "alice/research", "ask"),
    ("revert", "abc123", "alice/research", "ask"),
])
def test_decide(kind, detail, branch, want):
    assert decide(Action(kind=kind, detail=detail, reason="r"), branch) == want


@pytest.mark.parametrize("kind", ["push", "commit", "pull_rebase"])
def test_a_force_flag_anywhere_in_the_detail_is_always_denied(kind):
    assert decide(Action(kind=kind, detail="push --force origin main", reason="r"), "alice/research") == "deny"


def test_force_denial_is_case_insensitive():
    assert decide(Action(kind="push", detail="FORCE push", reason="r"), "alice/research") == "deny"
