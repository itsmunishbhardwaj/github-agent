import subprocess
from types import SimpleNamespace

import pytest

from github_agent import github
from github_agent.github import GitHubClient
from github_agent.models import PRDraft

from .fakes import FakePR, FakeRepo, issue_comment, review


def client(*prs):
    repo = FakeRepo(prs)
    return GitHubClient(repo), repo


def test_no_open_pr_for_the_branch_means_none():
    c, _ = client()
    assert c.pr_for_branch("alice/research") is None


def test_it_looks_up_open_prs_from_the_owner_and_branch():
    c, repo = client()
    c.pr_for_branch("alice/research")
    assert repo.pull_query == ("open", "alice-gh:alice/research")


@pytest.mark.parametrize("reviews,want", [
    ([], "pending"),
    ([review("alice-gh", "APPROVED"), review("bob", "COMMENTED")], "pending"),  # own approval and comments are not consent
    ([review("bob", "APPROVED")], "approved"),
    ([review("bob", "APPROVED"), review("carol", "CHANGES_REQUESTED")], "changes_requested"),
    ([review("bob", "CHANGES_REQUESTED"), review("bob", "APPROVED")], "approved"),  # a reviewer's latest review wins
    ([review("bob", "APPROVED"), review("bob", "CHANGES_REQUESTED")], "changes_requested"),
])
def test_consent_is_derived_from_each_other_reviewers_latest_review(reviews, want):
    c, _ = client(FakePR(7, "alice-gh", reviews))
    state = c.pr_for_branch("alice/research")
    assert state.consent == want and state.number == 7 and state.url == "https://github.test/pr/1"


def test_open_pr_appends_the_consent_questions_as_a_checklist():
    c, repo = client()
    number = c.open_pr("alice/research", "main", PRDraft(title="t", body_md="## Summary\nx", consent_questions=["agree on 40C?", "rerun?"]))
    made = repo.created[0]
    assert number == 101 and (made["head"], made["base"], made["title"]) == ("alice/research", "main", "t")
    assert made["body"].endswith("## Consent requested\n- [ ] agree on 40C?\n- [ ] rerun?")


def test_comment_posts_on_the_pull_request():
    pr = FakePR(7, "alice-gh")
    c, _ = client(pr)
    c.comment(7, "hello")
    assert pr.comments == ["hello"]


def test_status_uses_the_consent_context_and_truncates_the_description():
    c, repo = client()
    c.set_status("abc", "pending", "x" * 200)
    st = repo.commits["abc"].statuses[0]
    assert st["context"] == "github-agent/consent" and st["state"] == "pending" and len(st["description"]) == 140


def test_merge_uses_a_merge_commit_so_per_author_history_survives():
    pr = FakePR(7, "alice-gh")
    c, _ = client(pr)
    c.merge(7)
    assert pr.merged_with == "merge"


def test_token_prefers_the_environment_then_the_gh_cli(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert github.github_token() == "from-env"
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="from-gh\n"))
    assert github.github_token() == "from-gh"


def test_pr_comments_excludes_the_prs_own_author(monkeypatch):
    pr = FakePR(7, "alice-gh", issue_comments=[
        issue_comment("alice-gh", "my own note", "2026-01-01T00:00:00"),
        issue_comment("bob", "have you tried 50C?", "2026-01-02T00:00:00"),
    ])
    c, _ = client(pr)
    comments = c.pr_comments(7)
    assert [(x.author, x.body) for x in comments] == [("bob", "have you tried 50C?")]


def test_pr_comments_only_returns_comments_after_the_given_cutoff(monkeypatch):
    pr = FakePR(7, "alice-gh", issue_comments=[
        issue_comment("bob", "first", "2026-01-01T00:00:00"),
        issue_comment("bob", "second", "2026-01-02T00:00:00"),
    ])
    c, _ = client(pr)
    assert [x.body for x in c.pr_comments(7, since="2026-01-01T00:00:00")] == ["second"]
    assert [x.body for x in c.pr_comments(7, since=None)] == ["first", "second"]
