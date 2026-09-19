import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

import git

if TYPE_CHECKING:
    from .github import GitHubClient


@dataclass
class Config:
    main: str
    repo: str  # "owner/name"
    members: dict[str, str]  # researcher -> their long-lived branch

    def other_branch(self, mine: str) -> str:
        others = [b for b in self.members.values() if b != mine]
        if mine not in self.members.values() or len(others) != 1:
            raise ValueError(f"{mine!r} is not one of the two member branches {list(self.members.values())}")
        return others[0]


@dataclass
class Ctx:
    repo: git.Repo
    gh: "GitHubClient"
    db: sqlite3.Connection
    cfg: Config
