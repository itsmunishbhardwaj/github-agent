import pytest

from github_agent.context import Config

CFG = Config(main="main", repo="o/r", members={"alice": "alice/research", "bob": "bob/research"})


def test_other_branch_is_the_collaborators(  ):
    assert CFG.other_branch("alice/research") == "bob/research"
    assert CFG.other_branch("bob/research") == "alice/research"


def test_other_branch_rejects_a_branch_that_is_not_a_member_branch():
    with pytest.raises(ValueError, match="not one of the two member branches"):
        CFG.other_branch("alice/scratch")


def test_load_ctx_reads_config_env_and_opens_the_db(research_repo, monkeypatch):
    from github_agent import context, github

    (research_repo / ".github-agent").mkdir(exist_ok=True)
    (research_repo / ".github-agent" / "config.toml").write_text(
        'main = "main"\nrepo = "o/r"\n\n[members]\nalice = "alice/research"\nbob = "bob/research"\n'
    )
    (research_repo / ".env").write_text("RESEARCHER_TEST_VAR=from-dotenv\n")
    monkeypatch.setenv("RESEARCHER_TEST_VAR", "x")
    monkeypatch.delenv("RESEARCHER_TEST_VAR")  # registers cleanup so the .env value cannot leak into other tests
    monkeypatch.setattr(github.GitHubClient, "connect", classmethod(lambda cls, full_name, token=None: ("connected", full_name)))
    monkeypatch.chdir(research_repo)
    ctx = context.load_ctx()
    assert ctx.cfg == CFG
    assert ctx.gh == ("connected", "o/r")
    assert ctx.repo.active_branch.name == "alice/research"
    assert (research_repo / ".github-agent" / "state.db").exists()
    import os
    assert os.environ["RESEARCHER_TEST_VAR"] == "from-dotenv"
