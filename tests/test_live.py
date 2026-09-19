"""Opt-in: calls the real Claude API. Run with `pytest -m live`. Needs ANTHROPIC_API_KEY (env or ./.env)."""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from researcher import llm
from researcher.index import index_branches
from researcher.reconcile import build_input, reconcile_branches
from researcher.store import claims_by_id

pytestmark = pytest.mark.live


def test_seeded_contradiction_is_flagged_blocking_and_cites_both_researchers(ctx):
    load_dotenv(Path(__file__).parents[1] / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("no ANTHROPIC_API_KEY")
    llm.get_client.cache_clear()
    index_branches(ctx, ["alice/research", "main", "bob/research"])
    draft = reconcile_branches(build_input(ctx.db, "main", "alice/research", "bob/research"))
    blocking = [c for c in draft.conflicts if c.severity == "blocking"]
    assert blocking, draft
    claims = claims_by_id(ctx.db)
    assert {"Alice", "Bob"} <= {claims[i].author for c in blocking for i in c.claim_ids}
