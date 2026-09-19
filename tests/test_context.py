import pytest

from researcher.context import Config

CFG = Config(main="main", repo="o/r", members={"alice": "alice/research", "bob": "bob/research"})


def test_other_branch_is_the_collaborators(  ):
    assert CFG.other_branch("alice/research") == "bob/research"
    assert CFG.other_branch("bob/research") == "alice/research"


def test_other_branch_rejects_a_branch_that_is_not_a_member_branch():
    with pytest.raises(ValueError, match="not one of the two member branches"):
        CFG.other_branch("alice/scratch")
