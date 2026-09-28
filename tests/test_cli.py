import git
import pytest
import typer
from typer.testing import CliRunner

from github_agent import cli
from github_agent import index as index_mod
from github_agent.loop import Entry
from github_agent.models import Claim

from .conftest import make_conflict, make_output
from .fakes import FakeGH
from .gitutil import commit_file, run

runner = CliRunner()


@pytest.fixture
def wired(ctx, monkeypatch):
    """Real git repo + db; only Claude (claim extraction, reconcile) and GitHub are faked."""
    monkeypatch.setattr(cli, "load_ctx", lambda: ctx)
    monkeypatch.setattr(
        index_mod, "extract_claims",
        lambda path, text, commit, author: [
            Claim(id=f"{path}:{i}", text=line, kind="finding", source_path=path, line_start=i, line_end=i, commit=commit, author=author)
            for i, line in enumerate(text.splitlines(), 1) if line and not line.startswith("#")
        ],
    )
    monkeypatch.setattr(
        cli, "reconcile_branches",
        lambda inp: make_output([make_conflict(["notes.md:3", "b.md:1"])], title="add thermal results"),
    )
    ctx.gh = FakeGH()
    return ctx


def test_blame_prints_sha_author_line_and_text(wired):
    r = runner.invoke(cli.app, ["blame", "notes.md"])
    assert r.exit_code == 0
    assert "Carol" in r.output and "Alice" in r.output and "Baseline finding one." in r.output


def test_history_lists_commits_newest_first(wired):
    r = runner.invoke(cli.app, ["history", "notes.md"])
    assert r.exit_code == 0
    assert r.output.index("alice result") < r.output.index("base")


def test_revert_undoes_a_commit_as_a_new_commit(wired, research_repo):
    commit_file(research_repo, "oops.md", "x\n", "oops")
    sha = git.Repo(research_repo).head.commit.hexsha
    r = runner.invoke(cli.app, ["revert", sha])
    assert r.exit_code == 0 and "reverted" in r.output
    assert not (research_repo / "oops.md").exists()


def test_reconcile_prints_the_draft_pr_and_cites_both_authors_without_touching_github(wired):
    r = runner.invoke(cli.app, ["reconcile"])
    assert r.exit_code == 0
    assert "add thermal results" in r.output and "blocking" in r.output
    assert "notes.md:3" in r.output and "Alice" in r.output and "b.md:1" in r.output and "Bob" in r.output
    assert wired.gh.calls == []


def test_pr_refuses_to_run_with_uncommitted_changes(wired, research_repo):
    (research_repo / "notes.md").write_text("dirty\n")
    r = runner.invoke(cli.app, ["pr"], input="y\n")
    assert r.exit_code == 1 and "uncommitted" in r.output
    assert wired.gh.calls == []


def test_declining_the_confirmation_pushes_and_opens_nothing(wired, research_repo):
    commit_file(research_repo, "notes.md", "# Notes\nBaseline finding one.\nAlice: effect vanishes above 40C.\nnew\n", "more")
    r = runner.invoke(cli.app, ["pr"], input="n\n")
    assert r.exit_code != 0
    assert wired.gh.calls == []
    assert run(research_repo, "git", "rev-parse", "origin/alice/research").strip() != git.Repo(research_repo).head.commit.hexsha


def test_confirming_pushes_the_branch_opens_the_pr_comments_and_sets_pending_consent(wired, research_repo):
    commit_file(research_repo, "notes.md", "# Notes\nBaseline finding one.\nAlice: effect vanishes above 40C.\nnew\n", "more")
    head = git.Repo(research_repo).head.commit.hexsha
    r = runner.invoke(cli.app, ["pr"], input="y\n")
    assert r.exit_code == 0 and "opened PR #7" in r.output
    assert run(research_repo, "git", "--git-dir", str(research_repo.parent / "origin.git"), "rev-parse", "alice/research").strip() == head
    kinds = [c[0] for c in wired.gh.calls]
    assert kinds == ["open_pr", "comment", "set_status"]
    assert wired.gh.calls[0][1:] == ("alice/research", "main", "add thermal results")
    assert "`notes.md:3` Alice" in wired.gh.calls[1][2]
    assert wired.gh.calls[2][1:3] == (head, "pending")


def test_init_writes_config_ignore_file_and_gitignore_entries_and_is_not_rerunnable(tmp_path, monkeypatch):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    run(fresh, "git", "init", "-q")
    monkeypatch.chdir(fresh)
    args = ["init", "--repo", "o/r", "--mine", "alice/research", "--theirs", "bob/research"]
    r = runner.invoke(cli.app, args)
    assert r.exit_code == 0 and "branch protection" in r.output.lower()
    cfg = (fresh / ".github-agent" / "config.toml").read_text()
    assert 'repo = "o/r"' in cfg and '"alice/research"' in cfg and '"bob/research"' in cfg
    assert (fresh / ".github-agentignore").exists()
    gi = (fresh / ".gitignore").read_text().splitlines()
    assert ".env" in gi and ".github-agent/state.db" in gi
    again = runner.invoke(cli.app, args)
    assert again.exit_code == 1 and "already initialised" in again.output
    assert (fresh / ".gitignore").read_text().splitlines().count(".env") == 1


def test_confirm_shows_the_draft_before_asking_when_opening_a_pr(wired, monkeypatch):
    wired.draft = make_output([make_conflict(["notes.md:3", "b.md:1"])], title="add thermal results")
    shown = []
    monkeypatch.setattr(cli, "_show", lambda draft, claims: shown.append(draft))
    monkeypatch.setattr(typer, "confirm", lambda msg: True)
    assert cli._confirm(cli.Action(kind="open_pr", detail="", reason="ask for consent"), wired) is True
    assert shown == [wired.draft]


def test_confirm_does_not_show_a_draft_for_other_action_kinds(wired, monkeypatch):
    shown = []
    monkeypatch.setattr(cli, "_show", lambda draft, claims: shown.append(draft))
    monkeypatch.setattr(typer, "confirm", lambda msg: True)
    cli._confirm(cli.Action(kind="push", detail="", reason="share work"), wired)
    assert shown == []


def test_sync_prints_each_journal_entry_and_uses_a_stay_synced_goal(wired, monkeypatch):
    entries = [
        Entry(step=0, action=cli.Action(kind="fetch", detail="", reason="stay current"), verdict="auto", ok=True, observation="fetched"),
        Entry(step=0, action=cli.Action(kind="push", detail="", reason="share work"), verdict="ask", ok=False, observation="declined by user"),
    ]
    seen = {}

    def fake_run_loop(ctx, goal, confirm, max_steps):
        seen.update(goal=goal, confirm=confirm, max_steps=max_steps)
        return entries

    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    r = runner.invoke(cli.app, ["sync"])
    assert r.exit_code == 0
    assert "[auto] fetch: fetched" in r.output and "[ask] push: declined by user" in r.output
    assert "rebased" in seen["goal"] and seen["confirm"] is cli._confirm and seen["max_steps"] == 6


def test_merge_uses_a_consent_goal_and_a_custom_max_steps(wired, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "run_loop", lambda ctx, goal, confirm, max_steps: seen.update(goal=goal, max_steps=max_steps) or [])
    r = runner.invoke(cli.app, ["merge", "--max-steps", "2"])
    assert r.exit_code == 0
    assert "approved" in seen["goal"] and seen["max_steps"] == 2


def test_watch_delegates_to_watch_loop_with_the_given_interval(wired, monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "watch_loop", lambda ctx, interval, confirm: seen.update(interval=interval, confirm=confirm))
    r = runner.invoke(cli.app, ["watch", "--interval", "5"])
    assert r.exit_code == 0 and "watching every 5s" in r.output
    assert seen["interval"] == 5 and seen["confirm"] is cli._confirm
