import git
import pytest

from researcher.gitops import blame_lines, dirty_paths, file_history, revert_commit, sidecar_for

from .gitutil import commit_file, run


def test_dirty_paths_lists_modified_and_untracked_files(research_repo):
    (research_repo / "notes.md").write_text("changed\n")
    (research_repo / "new.md").write_text("x\n")
    assert sorted(dirty_paths(git.Repo(research_repo))) == ["new.md", "notes.md"]


def test_sidecar_for_text_is_the_file_and_for_binary_docs_the_committed_extract():
    assert sidecar_for("notes.md") == "notes.md"
    assert sidecar_for("papers/p.pdf") == ".researcher/text/papers/p.pdf.md"


def test_blame_attributes_each_line_to_the_author_who_wrote_it(research_repo):
    commit_file(research_repo, "notes.md", "# Notes\nBaseline finding one.\nAlice: effect vanishes above 40C.\nBob: caveat.\n", "bob note", author="Bob")
    got = [(b.line, b.author) for b in blame_lines(git.Repo(research_repo), "notes.md")]
    assert got == [(1, "Carol"), (2, "Carol"), (3, "Alice"), (4, "Bob")]


def test_blame_of_a_binary_doc_reads_its_committed_sidecar(research_repo):
    commit_file(research_repo, "paper.pdf", b"%PDF-binary", "add paper", author="Alice")
    commit_file(research_repo, ".researcher/text/paper.pdf.md", "Claim from the paper.\n", "extract paper", author="Bob")
    assert [(b.line, b.author) for b in blame_lines(git.Repo(research_repo), "paper.pdf")] == [(1, "Bob")]


def test_blame_at_an_earlier_rev(research_repo):
    repo = git.Repo(research_repo)
    lines = blame_lines(repo, "notes.md", rev="main")
    assert [b.line for b in lines] == [1, 2] and {b.author for b in lines} == {"Carol"}


def test_file_history_is_newest_first(research_repo):
    commit_file(research_repo, "notes.md", "# Notes\nBaseline finding one.\nAlice: effect vanishes above 40C.\nmore\n", "more notes", author="Bob")
    subjects = [h[3] for h in file_history(git.Repo(research_repo), "notes.md")]
    assert subjects == ["more notes", "alice result", "base"]


def test_revert_adds_a_commit_that_undoes_the_change_and_keeps_history(research_repo):
    repo = git.Repo(research_repo)
    commit_file(research_repo, "extra.md", "oops\n", "oops")
    bad = repo.head.commit.hexsha
    before = len(list(repo.iter_commits()))
    msg = revert_commit(repo, bad)
    assert not (research_repo / "extra.md").exists()
    assert len(list(repo.iter_commits())) == before + 1
    assert msg.startswith(f"reverted {bad[:8]}")


def test_a_conflicting_revert_aborts_and_leaves_a_clean_tree(research_repo):
    repo = git.Repo(research_repo)
    commit_file(research_repo, "notes.md", "# Notes\nfirst edit\n", "edit 1")
    first = repo.head.commit.hexsha
    commit_file(research_repo, "notes.md", "# Notes\nsecond edit\n", "edit 2")
    with pytest.raises(git.GitCommandError):
        revert_commit(repo, first)
    assert not repo.is_dirty()
    assert not (research_repo / ".git" / "REVERT_HEAD").exists()
