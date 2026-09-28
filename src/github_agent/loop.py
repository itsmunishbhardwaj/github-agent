import time
from collections.abc import Callable
from pathlib import Path

import git
from pydantic import BaseModel

from .context import Ctx
from .extract import write_sidecars
from .github import PRState
from .gitops import dirty_paths, revert_commit
from .index import index_branches
from .llm import ask
from .policy import Action, decide
from .reconcile import build_input, reconcile_branches
from .render import render_conflict_comment
from .store import claims_by_id, save_journal


class Snapshot(BaseModel):
    branch: str
    ahead: int
    behind: int
    dirty_paths: list[str]
    collaborator_new_commits: list[str]
    pr: PRState | None


class Plan(BaseModel):
    done: bool
    actions: list[Action]


class Reflection(BaseModel):
    goal_met: bool
    lesson: str


class Entry(BaseModel):
    step: int
    action: Action
    verdict: str
    ok: bool
    observation: str


PLAN_SYSTEM = """You plan the next actions of a git + GitHub agent that helps two collaborators sync research.
Choose actions in order from the allowed kinds. Plan `reconcile` before `open_pr`, and `push` before `open_pr`.
Plan merge_pr only if snapshot.pr.consent == 'approved'. Never plan force pushes. Set done=true when the goal is already met."""
REFLECT_SYSTEM = """Compare before/after snapshots and the executed entries. goal_met=true only if the goal now holds.
lesson: one sentence a future run should remember (empty if nothing)."""


def sense(ctx: Ctx) -> Snapshot:
    repo, cfg = ctx.repo, ctx.cfg
    repo.remotes.origin.fetch()
    branch = repo.active_branch.name
    theirs = cfg.other_branch(branch)
    seen = ctx.db.execute("SELECT head_sha FROM seen_heads WHERE branch = ?", (theirs,)).fetchone()
    rng = f"{seen[0]}..origin/{theirs}" if seen else f"origin/{cfg.main}..origin/{theirs}"
    index_branches(ctx, [branch, cfg.main, theirs])
    ahead, behind = (int(n) for n in repo.git.rev_list("--left-right", "--count", f"{branch}...origin/{cfg.main}").split())
    return Snapshot(
        branch=branch, ahead=ahead, behind=behind, dirty_paths=dirty_paths(repo),
        collaborator_new_commits=[c.summary for c in repo.iter_commits(rng)],
        pr=ctx.gh.pr_for_branch(branch),
    )


def execute(a: Action, ctx: Ctx) -> str:
    repo, gh, branch = ctx.repo, ctx.gh, ctx.repo.active_branch.name
    match a.kind:
        case "fetch":
            repo.remotes.origin.fetch()
            return "fetched"
        case "extract":
            return f"{len(write_sidecars(Path(repo.working_dir)))} sidecars written"
        case "reconcile":
            theirs = ctx.cfg.other_branch(branch)
            ctx.draft = reconcile_branches(build_input(ctx.db, ctx.cfg.main, branch, theirs))
            n_block = sum(c.severity == "blocking" for c in ctx.draft.conflicts)
            return f"{len(ctx.draft.conflicts)} conflicts ({n_block} blocking); {ctx.draft.recommendation}; title: {ctx.draft.pr.title}"
        case "commit":
            paths = dirty_paths(repo)
            if not paths:
                return "nothing to commit"
            repo.git.add("--", *paths)  # explicit paths, never `git add -A`
            repo.git.commit("-m", a.detail)
            return repo.head.commit.hexsha[:8]
        case "pull_rebase":
            try:
                repo.git.pull("--rebase", "origin", branch)
            except git.GitCommandError:
                repo.git.rebase("--abort")
                raise
            return "rebased"
        case "push":
            repo.git.push("-u", "origin", branch)  # never --force
            return "pushed"
        case "open_pr":
            out = ctx.draft
            if out is None:
                raise RuntimeError("no PR draft: run `reconcile` first")
            number = gh.open_pr(branch, ctx.cfg.main, out.pr)
            gh.comment(number, render_conflict_comment(out, claims_by_id(ctx.db)))
            gh.set_status(repo.head.commit.hexsha, "pending", "Awaiting collaborator consent")
            return f"opened PR #{number}"
        case "comment_pr":
            pr = gh.pr_for_branch(branch)
            gh.comment(pr.number, a.detail)
            return "commented"
        case "set_status":
            gh.set_status(repo.head.commit.hexsha, "pending", a.detail)
            return "status set"
        case "merge_pr":
            pr = gh.pr_for_branch(branch)
            if pr is None or pr.consent != "approved":
                raise PermissionError("collaborator approval missing")
            gh.merge(pr.number)
            gh.set_status(repo.head.commit.hexsha, "success", "Consent given, merged")
            return f"merged PR #{pr.number}"
        case "revert":
            return revert_commit(repo, a.detail)


def run_loop(ctx: Ctx, goal: str, confirm: Callable[[Action, Ctx], bool], max_steps: int = 6) -> list[Entry]:
    journal: list[Entry] = []
    snap = sense(ctx)
    for step in range(max_steps):
        plan = ask(
            PLAN_SYSTEM,
            {"goal": goal, "snapshot": snap.model_dump(), "journal": [e.model_dump() for e in journal[-5:]]},
            Plan,
        )
        if plan.done or not plan.actions:
            break
        entries: list[Entry] = []
        for action in plan.actions:
            verdict = decide(action, snap.branch)
            if verdict == "deny" or (verdict == "ask" and not confirm(action, ctx)):
                note = "denied by policy" if verdict == "deny" else "declined by user"
                entries.append(Entry(step=step, action=action, verdict=verdict, ok=False, observation=note))
                continue
            try:
                obs, ok = execute(action, ctx), True
            except Exception as e:  # noqa: BLE001 -- any action can fail many ways; that becomes an observation, not a crash
                obs, ok = f"{type(e).__name__}: {e}", False
            entries.append(Entry(step=step, action=action, verdict=verdict, ok=ok, observation=obs))
        after = sense(ctx)
        refl = ask(
            REFLECT_SYSTEM,
            {"goal": goal, "before": snap.model_dump(), "after": after.model_dump(), "entries": [e.model_dump() for e in entries]},
            Reflection,
        )
        journal += entries
        save_journal(ctx.db, goal, entries, refl.lesson)
        snap = after
        if refl.goal_met:
            break
    return journal


def watch_loop(ctx: Ctx, interval: int, confirm: Callable[[Action, Ctx], bool], max_iterations: int | None = None) -> None:
    """Polls until the snapshot changes, then runs one loop. max_iterations bounds it for tests; None means forever."""
    last = None
    i = 0
    while max_iterations is None or i < max_iterations:
        snap = sense(ctx)
        key = (snap.behind, tuple(snap.dirty_paths), tuple(snap.collaborator_new_commits), snap.pr and snap.pr.consent)
        if key != last:
            run_loop(ctx, "Keep my branch committed and rebased on main; report collaborator changes and PR review events.", confirm)
            last = key
        i += 1
        if max_iterations is None or i < max_iterations:
            time.sleep(interval)
