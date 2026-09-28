from github_agent.render import render_conflict_comment

from .conftest import make_claim, make_conflict, make_output

CLAIMS = {
    "m1": make_claim("m1", path="notes.md", line=3, author="Alice", commit="abc12345"),
    "m2": make_claim("m2", path="b.md", line=1, author="Bob", commit="def67890"),
}


def test_comment_cites_each_claim_by_file_line_author_and_commit_and_asks_for_consent():
    md = render_conflict_comment(make_output([make_conflict(["m1", "m2"])]), CLAIMS)
    assert "BLOCKING" in md and "contradiction" in md
    assert "`notes.md:3` Alice @ abc12345" in md and "`b.md:1` Bob @ def67890" in md
    assert "**discuss**" in md and "- [ ] ok?" in md and "Approve this PR" in md


def test_no_conflicts_says_so_in_the_report():
    assert "No conflicts found." in render_conflict_comment(make_output(), CLAIMS)


def test_pipes_and_newlines_in_cells_do_not_break_the_table():
    c = make_conflict(["m1", "m2"])
    c.explanation = "a | b\nc"
    md = render_conflict_comment(make_output([c]), CLAIMS)
    assert "a \\| b c" in md


def test_a_claim_id_missing_from_the_index_is_skipped_not_fatal():
    md = render_conflict_comment(make_output([make_conflict(["m1", "ghost"])]), CLAIMS)
    assert "`notes.md:3`" in md and "ghost" not in md
