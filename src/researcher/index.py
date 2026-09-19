from pathlib import Path

from .context import Ctx
from .extract import extract_claims, ignore_spec
from .gitops import blame_lines, sidecar_for
from .store import blob_known, record_branch_file, record_head, save_claims


def _ref(ctx: Ctx, branch: str) -> str:
    return branch if branch == ctx.repo.active_branch.name else f"origin/{branch}"


def _index_commit(ctx: Ctx, label: str, commit, spec) -> None:
    for item in commit.tree.traverse():
        if item.type != "blob" or item.path.startswith(".researcher/") or spec.match_file(item.path):
            continue
        try:
            text_blob = commit.tree / sidecar_for(item.path)
        except KeyError:
            continue  # not text and no sidecar yet
        if not blob_known(ctx.db, text_blob.hexsha):
            blame = {b.line: b for b in blame_lines(ctx.repo, item.path, rev=commit.hexsha)}
            claims = []
            for c in extract_claims(item.path, text_blob.data_stream.read().decode(), commit.hexsha[:8], commit.author.name):
                b = blame.get(c.line_start)
                claims.append(c.model_copy(update={"commit": b.sha, "author": b.author}) if b else c)
            save_claims(ctx.db, text_blob.hexsha, claims)
        record_branch_file(ctx.db, label, item.path, text_blob.hexsha, commit.hexsha)


def index_branches(ctx: Ctx, branches: list[str]) -> None:
    """Idempotent. Indexes each branch tip plus its merge-base with main, extracting only new text blobs."""
    spec = ignore_spec(Path(ctx.repo.working_dir))
    main = ctx.repo.commit(_ref(ctx, ctx.cfg.main))
    for branch in branches:
        commit = ctx.repo.commit(_ref(ctx, branch))
        _index_commit(ctx, branch, commit, spec)
        record_head(ctx.db, branch, commit.hexsha, commit.author.name)
        if branch != ctx.cfg.main:
            _index_commit(ctx, f"{branch}@base", ctx.repo.merge_base(commit, main)[0], spec)
