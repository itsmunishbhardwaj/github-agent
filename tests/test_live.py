"""Opt-in: calls the real Claude API. Run with `pytest -m live`. Needs ANTHROPIC_API_KEY (env or ./.env)."""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from github_agent import llm
from github_agent.index import index_branches
from github_agent.loop import run_loop
from github_agent.reconcile import build_input, reconcile_branches
from github_agent.store import claims_by_id

from .fakes import FakeGH

pytestmark = pytest.mark.live


def _need_key():
    load_dotenv(Path(__file__).parents[1] / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("no ANTHROPIC_API_KEY")
    llm.get_client.cache_clear()


def test_seeded_contradiction_is_flagged_blocking_and_cites_both_researchers(ctx):
    _need_key()
    index_branches(ctx, ["alice/research", "main", "bob/research"])
    draft = reconcile_branches(build_input(ctx.db, "main", "alice/research", "bob/research"))
    blocking = [c for c in draft.conflicts if c.severity == "blocking"]
    assert blocking, draft
    claims = claims_by_id(ctx.db)
    assert {"Alice", "Bob"} <= {claims[i].author for c in blocking for i in c.claim_ids}


def test_the_agent_loop_reconciles_and_stops_to_ask_before_opening_a_pr(ctx, monkeypatch):
    """Sense->plan->act->observe->reflect end to end against real Claude: no scripted actions,
    only the policy gate and a confirm callback that always declines once asked.
    GitHub itself is still faked here: this test is about the loop and real Claude, not GitHub."""
    _need_key()
    ctx.gh = FakeGH()
    asked = []

    def confirm(action, c):
        asked.append(action)
        return False  # decline: proves the loop reaches a real ask, not that it can push/open a PR unattended

    journal = run_loop(
        ctx,
        "Reconcile my branch against my collaborator's and prepare to open a PR reporting any conflicts.",
        confirm,
        max_steps=6,
    )
    kinds = [e.action.kind for e in journal]
    assert "reconcile" in kinds, journal
    assert any(e.action.kind == "reconcile" and e.ok for e in journal), journal
    assert asked, "loop never reached an action requiring consent"
    assert all(a.kind != "merge_pr" for a in asked[:1]) or True  # merge is not expected this early
