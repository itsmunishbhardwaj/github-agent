from types import SimpleNamespace

import git
import pytest

from github_agent import index as index_mod
from github_agent import loop
from github_agent.loop import Entry, Plan, Reflection, Snapshot, execute, run_loop, sense, watch_loop
from github_agent.models import Claim
from github_agent.policy import Action

from .conftest import make_conflict, make_output
from .fakes import FakeGH
from .gitutil import commit_file, run


@pytest.fixture
def wired(ctx, monkeypatch):
    """Real git repo + db; only Claude (claim extraction) and GitHub are faked."""
    monkeypatch.setattr(
        index_mod, "extract_claims",
        lambda path, text, commit, author: [
            Claim(id=f"{path}:{i}", text=line, kind="finding", source_path=path, line_start=i, line_end=i, commit=commit, author=author)
            for i, line in enumerate(text.splitlines(), 1) if line and not line.startswith("#")
        ],
    )
    ctx.gh = FakeGH()
    ctx.draft = None
    return ctx


class FakePlanner:
    """Scripted stand-in for loop.ask: returns each queued Plan/Reflection in order."""

    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []

    def __call__(self, system, payload, schema):
        self.calls.append((system, payload, schema))
        return self.outputs.pop(0)


# ---- sense ----

def test_sense_reports_branch_dirty_paths_and_no_open_pr(wired):
    snap = sense(wired)
    assert snap.branch == "alice/research" and snap.dirty_paths == [] and snap.pr is None


def test_sense_reports_uncommitted_changes(wired, research_repo):
    (research_repo / "scratch.md").write_text("x\n")
    assert sense(wired).dirty_paths == ["scratch.md"]


def test_sense_lists_the_collaborators_commits_since_the_fork_on_first_run(wired):
    snap = sense(wired)
    assert snap.collaborator_new_commits == ["bob result"]


def test_sense_only_lists_collaborator_commits_pushed_since_the_last_sense(wired, research_repo, tmp_path):
    sense(wired)  # records bob's current head as seen
    second = tmp_path / "second"
    run(tmp_path, "git", "clone", "-q", str(tmp_path / "origin.git"), str(second))
    run(second, "git", "checkout", "-q", "bob/research")
    commit_file(second, "b.md", "Bob: effect persists to 60C.\nnew line\n", "bob follow-up", author="Bob")
    run(second, "git", "push", "-q", "origin", "bob/research")
    assert sense(wired).collaborator_new_commits == ["bob follow-up"]


# ---- execute ----

def test_execute_fetch(wired):
    assert execute(Action(kind="fetch", detail="", reason="stay current"), wired) == "fetched"


def test_execute_extract_reports_how_many_sidecars_were_written(wired):
    assert execute(Action(kind="extract", detail="", reason="index binary docs"), wired) == "0 sidecars written"


def test_execute_reconcile_sets_the_draft_and_summarizes_it(wired, monkeypatch):
    sense(wired)  # populates seen_heads/claims so build_input has something to read
    draft = make_output([make_conflict(["a", "b"])], recommendation="discuss", title="add results")
    monkeypatch.setattr(loop, "reconcile_branches", lambda inp: draft)
    obs = execute(Action(kind="reconcile", detail="", reason="check for conflicts"), wired)
    assert wired.draft is draft
    assert obs == "1 conflicts (1 blocking); discuss; title: add results"


def test_execute_commit_with_nothing_dirty(wired):
    assert execute(Action(kind="commit", detail="wip", reason="save progress"), wired) == "nothing to commit"


def test_execute_commit_adds_only_dirty_paths_and_commits(wired, research_repo):
    (research_repo / "scratch.md").write_text("x\n")
    before = len(list(wired.repo.iter_commits()))
    sha = execute(Action(kind="commit", detail="add scratch notes", reason="checkpoint"), wired)
    assert len(sha) == 8
    assert len(list(wired.repo.iter_commits())) == before + 1
    assert wired.repo.head.commit.message.strip() == "add scratch notes"


def test_execute_pull_rebase_fast_forwards_cleanly(wired):
    assert execute(Action(kind="pull_rebase", detail="", reason="stay current"), wired) == "rebased"


def test_execute_pull_rebase_aborts_on_conflict_and_reraises(wired, research_repo, tmp_path):
    second = tmp_path / "second"
    run(tmp_path, "git", "clone", "-q", str(tmp_path / "origin.git"), str(second))
    run(second, "git", "checkout", "-q", "alice/research")
    commit_file(second, "notes.md", "# Notes\nremote edit\n", "remote edit", author="Alice")
    run(second, "git", "push", "-q", "origin", "alice/research")
    commit_file(research_repo, "notes.md", "# Notes\nlocal edit\n", "local edit", author="Alice")
    with pytest.raises(git.GitCommandError):
        execute(Action(kind="pull_rebase", detail="", reason="stay current"), wired)
    assert not wired.repo.is_dirty()
    assert not (research_repo / ".git" / "rebase-merge").exists()


def test_execute_push(wired, research_repo):
    commit_file(research_repo, "scratch.md", "x\n", "scratch")
    head = wired.repo.head.commit.hexsha
    assert execute(Action(kind="push", detail="", reason="share work"), wired) == "pushed"
    assert run(research_repo, "git", "--git-dir", str(research_repo.parent / "origin.git"), "rev-parse", "alice/research").strip() == head


def test_execute_open_pr_without_a_draft_refuses(wired):
    with pytest.raises(RuntimeError, match="reconcile"):
        execute(Action(kind="open_pr", detail="", reason="ask for consent"), wired)


def test_execute_open_pr_opens_comments_and_sets_pending_status(wired):
    wired.draft = make_output([make_conflict(["a", "b"])], title="add results")
    obs = execute(Action(kind="open_pr", detail="", reason="ask for consent"), wired)
    assert obs == "opened PR #7"
    kinds = [c[0] for c in wired.gh.calls]
    assert kinds == ["open_pr", "comment", "set_status"]
    assert wired.gh.calls[2][1:3] == (wired.repo.head.commit.hexsha, "pending")


def test_execute_comment_pr(wired):
    wired.gh.open_pr("alice/research", "main", make_output().pr)
    assert execute(Action(kind="comment_pr", detail="hello", reason="clarify"), wired) == "commented"
    assert wired.gh.calls[-1] == ("comment", 7, "hello")


def test_execute_set_status(wired):
    assert execute(Action(kind="set_status", detail="checking", reason="report progress"), wired) == "status set"
    assert wired.gh.calls[-1][2:] == ("pending", "checking")


def test_execute_merge_pr_refuses_without_consent(wired, monkeypatch):
    monkeypatch.setattr(wired.gh, "pr_for_branch", lambda b: SimpleNamespace(number=7, consent="pending"))
    with pytest.raises(PermissionError, match="approval"):
        execute(Action(kind="merge_pr", detail="", reason="finish up"), wired)


def test_execute_merge_pr_merges_once_approved(wired, monkeypatch):
    monkeypatch.setattr(wired.gh, "pr_for_branch", lambda b: SimpleNamespace(number=7, consent="approved"))
    merged = {}
    monkeypatch.setattr(wired.gh, "merge", lambda n: merged.setdefault("n", n))
    obs = execute(Action(kind="merge_pr", detail="", reason="finish up"), wired)
    assert obs == "merged PR #7" and merged["n"] == 7
    assert wired.gh.calls[-1][2:] == ("success", "Consent given, merged")


def test_execute_revert(wired, research_repo):
    commit_file(research_repo, "oops.md", "x\n", "oops")
    sha = wired.repo.head.commit.hexsha
    assert execute(Action(kind="revert", detail=sha, reason="undo"), wired).startswith(f"reverted {sha[:8]}")


# ---- run_loop ----

def always_confirm(action, ctx):
    return True


def never_confirm(action, ctx):
    return False


def test_run_loop_stops_immediately_when_the_planner_says_done(wired, monkeypatch):
    planner = FakePlanner(Plan(done=True, actions=[]))
    monkeypatch.setattr(loop, "ask", planner)
    assert run_loop(wired, "already synced", always_confirm) == []
    assert len(planner.calls) == 1


def test_run_loop_executes_an_auto_action_without_asking(wired, monkeypatch, research_repo):
    (research_repo / "scratch.md").write_text("x\n")
    plan = Plan(done=False, actions=[Action(kind="commit", detail="wip", reason="checkpoint")])
    planner = FakePlanner(plan, Reflection(goal_met=True, lesson=""))
    monkeypatch.setattr(loop, "ask", planner)
    asked = []
    journal = run_loop(wired, "commit my work", lambda a, c: asked.append(a) or True)
    assert asked == []  # commit on own branch is auto
    assert len(journal) == 1 and journal[0].verdict == "auto" and journal[0].ok is True


def test_run_loop_asks_before_a_push_and_records_a_decline(wired, monkeypatch):
    plan = Plan(done=False, actions=[Action(kind="push", detail="", reason="share work")])
    planner = FakePlanner(plan, Reflection(goal_met=True, lesson="user declined the push"))
    monkeypatch.setattr(loop, "ask", planner)
    journal = run_loop(wired, "share my branch", never_confirm)
    assert journal == [Entry(step=0, action=plan.actions[0], verdict="ask", ok=False, observation="declined by user")]


def test_run_loop_denies_a_force_push_without_asking(wired, monkeypatch):
    plan = Plan(done=False, actions=[Action(kind="push", detail="push --force", reason="overwrite")])
    planner = FakePlanner(plan, Reflection(goal_met=True, lesson=""))
    monkeypatch.setattr(loop, "ask", planner)
    asked = []
    journal = run_loop(wired, "force push", lambda a, c: asked.append(a) or True)
    assert asked == []
    assert journal[0].verdict == "deny" and journal[0].observation == "denied by policy"


def test_run_loop_turns_a_failed_action_into_an_observation_not_a_crash(wired, monkeypatch):
    plan = Plan(done=False, actions=[Action(kind="open_pr", detail="", reason="ask for consent")])
    planner = FakePlanner(plan, Reflection(goal_met=True, lesson="reconcile before opening a PR"))
    monkeypatch.setattr(loop, "ask", planner)
    journal = run_loop(wired, "open a pr", always_confirm)
    assert journal[0].ok is False and "reconcile" in journal[0].observation


def test_run_loop_writes_entries_and_lesson_to_the_journal(wired, monkeypatch):
    plan = Plan(done=False, actions=[Action(kind="fetch", detail="", reason="stay current")])
    planner = FakePlanner(plan, Reflection(goal_met=True, lesson="fetch first, always"))
    monkeypatch.setattr(loop, "ask", planner)
    run_loop(wired, "stay synced", always_confirm)
    row = wired.db.execute("SELECT goal, observation, lesson FROM journal").fetchone()
    assert row == ("stay synced", "fetched", "fetch first, always")


def test_run_loop_stops_at_max_steps_even_if_never_done(wired, monkeypatch):
    plan = Plan(done=False, actions=[Action(kind="fetch", detail="", reason="stay current")])
    planner = FakePlanner(*([plan, Reflection(goal_met=False, lesson="")] * 3))
    monkeypatch.setattr(loop, "ask", planner)
    journal = run_loop(wired, "never satisfied", always_confirm, max_steps=3)
    assert len(journal) == 3


# ---- watch_loop ----

def test_watch_loop_runs_once_per_distinct_snapshot_and_stops_after_n_iterations(wired, monkeypatch):
    snaps = [
        Snapshot(branch="alice/research", ahead=0, behind=0, dirty_paths=[], collaborator_new_commits=[], pr=None),
        Snapshot(branch="alice/research", ahead=0, behind=0, dirty_paths=[], collaborator_new_commits=[], pr=None),  # unchanged
        Snapshot(branch="alice/research", ahead=0, behind=1, dirty_paths=[], collaborator_new_commits=[], pr=None),  # changed
    ]
    monkeypatch.setattr(loop, "sense", lambda ctx: snaps.pop(0))
    runs = []
    monkeypatch.setattr(loop, "run_loop", lambda ctx, goal, confirm: runs.append(goal))
    monkeypatch.setattr(loop.time, "sleep", lambda s: None)
    watch_loop(wired, interval=1, confirm=always_confirm, max_iterations=3)
    assert len(runs) == 2
