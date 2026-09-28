import json
from pathlib import Path

import git
import typer

from .context import Ctx, load_ctx
from .gitops import blame_lines, dirty_paths, file_history, revert_commit
from .index import index_branches
from .loop import run_loop, watch_loop
from .models import Claim, ReconcileOutput
from .policy import Action
from .reconcile import build_input, reconcile_branches
from .render import render_conflict_comment
from .store import claims_by_id

app = typer.Typer(no_args_is_help=True)


def _member(branch: str) -> str:
    return f'{json.dumps(branch.replace("/", "-"))} = {json.dumps(branch)}'


def _show(draft: ReconcileOutput, claims: dict[str, Claim]) -> None:
    typer.echo(f"PR: {draft.pr.title}  [{draft.recommendation}]\n{draft.pr.body_md}\n")
    for c in draft.conflicts:
        typer.echo(f"{c.severity} {c.kind}: {c.explanation}")
        for i in c.claim_ids:
            if i in claims:
                k = claims[i]
                typer.echo(f"    {k.source_path}:{k.line_start}  {k.author} @ {k.commit}: {k.text}")
        typer.echo(f"    resolve: {c.suggested_resolution}")
    for q in draft.pr.consent_questions:
        typer.echo(f"ask: {q}")


def _reconcile(ctx) -> ReconcileOutput:
    mine = ctx.repo.active_branch.name
    theirs = ctx.cfg.other_branch(mine)
    ctx.repo.remotes.origin.fetch()
    index_branches(ctx, [mine, ctx.cfg.main, theirs])
    draft = reconcile_branches(build_input(ctx.db, ctx.cfg.main, mine, theirs))
    _show(draft, claims_by_id(ctx.db))
    return draft


@app.command()
def init(
    repo: str = typer.Option(..., help="GitHub owner/name"),
    mine: str = typer.Option(..., help="your long-lived research branch"),
    theirs: str = typer.Option(..., help="your collaborator's research branch"),
    main: str = "main",
) -> None:
    root = Path(git.Repo(search_parent_directories=True).working_dir)
    cfg = root / ".github-agent" / "config.toml"
    if cfg.exists():
        typer.echo("already initialised")
        raise typer.Exit(1)
    cfg.parent.mkdir(exist_ok=True)
    member = lambda b: f'{json.dumps(b.replace("/", "-"))} = {json.dumps(b)}'
    cfg.write_text(f"main = {json.dumps(main)}\nrepo = {json.dumps(repo)}\n\n[members]\n{member(mine)}\n{member(theirs)}\n")
    ignore = root / ".github-agentignore"
    if not ignore.exists():
        ignore.write_text("# paths here are never sent to the LLM (gitignore syntax)\n")
    gi = root / ".gitignore"
    existing = gi.read_text().splitlines() if gi.exists() else []
    missing = [line for line in (".env", ".github-agent/state.db") if line not in existing]
    if missing:
        gi.write_text("\n".join([*existing, *missing]) + "\n")
    typer.echo(
        f"Initialised. Next, on GitHub add a branch protection rule on {main} requiring 1 approving review: "
        "that rule is what enforces your collaborator's consent."
    )


@app.command()
def reconcile() -> None:
    """Dry run: show the conflict report and PR draft. Touches nothing on GitHub."""
    _reconcile(load_ctx())


@app.command()
def pr() -> None:
    """Reconcile against the collaborator's branch, then push and open a PR asking for their consent."""
    ctx = load_ctx()
    if dirty_paths(ctx.repo):
        typer.echo("uncommitted changes: commit them first")
        raise typer.Exit(1)
    draft = _reconcile(ctx)
    if not typer.confirm("Push my branch and open this PR?"):
        raise typer.Abort()
    branch = ctx.repo.active_branch.name
    ctx.repo.git.push("-u", "origin", branch)
    number = ctx.gh.open_pr(branch, ctx.cfg.main, draft.pr)
    ctx.gh.comment(number, render_conflict_comment(draft, claims_by_id(ctx.db)))
    ctx.gh.set_status(ctx.repo.head.commit.hexsha, "pending", "Awaiting collaborator consent")
    typer.echo(f"opened PR #{number}")


def _confirm(action: Action, ctx: Ctx) -> bool:
    if action.kind == "open_pr" and ctx.draft:
        _show(ctx.draft, claims_by_id(ctx.db))
    label = f": {action.detail}" if action.detail else ""
    return typer.confirm(f"{action.kind}{label}\n  why: {action.reason}\nProceed?")


@app.command()
def sync(max_steps: int = 6) -> None:
    """Agent loop: keep my branch committed and rebased, report what changed. Pushing still asks."""
    ctx = load_ctx()
    goal = "Keep my branch committed and rebased on main; report collaborator changes and any PR review events."
    for e in run_loop(ctx, goal, _confirm, max_steps=max_steps):
        typer.echo(f"[{e.verdict}] {e.action.kind}: {e.observation}")


@app.command()
def merge(max_steps: int = 6) -> None:
    """Agent loop: merge my open PR if, and only if, the collaborator has approved it."""
    ctx = load_ctx()
    for e in run_loop(ctx, "Merge my open PR if and only if the collaborator has approved it.", _confirm, max_steps=max_steps):
        typer.echo(f"[{e.verdict}] {e.action.kind}: {e.observation}")


@app.command()
def watch(interval: int = 60) -> None:
    """Poll git and GitHub every INTERVAL seconds; run the agent loop whenever something changes."""
    typer.echo(f"watching every {interval}s (ctrl-c to stop)")
    watch_loop(load_ctx(), interval, _confirm)


@app.command()
def history(path: str) -> None:
    for sha, author, date, subject in file_history(load_ctx().repo, path):
        typer.echo(f"{sha}  {date}  {author:<16} {subject}")


@app.command()
def blame(path: str) -> None:
    for b in blame_lines(load_ctx().repo, path):
        typer.echo(f"{b.sha} {b.author:<16} {b.line:>4}  {b.text}")


@app.command()
def revert(sha: str) -> None:
    """New commit that undoes <sha>. History is preserved."""
    typer.echo(revert_commit(load_ctx().repo, sha))
