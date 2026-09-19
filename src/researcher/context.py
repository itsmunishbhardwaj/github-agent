import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path

import git
from dotenv import load_dotenv

from .github import GitHubClient
from .store import open_db


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
    gh: GitHubClient
    db: sqlite3.Connection
    cfg: Config


def load_ctx() -> Ctx:
    repo = git.Repo(search_parent_directories=True)
    root = Path(repo.working_dir)
    load_dotenv(root / ".env")
    raw = tomllib.loads((root / ".researcher" / "config.toml").read_text())
    cfg = Config(main=raw["main"], repo=raw["repo"], members=raw["members"])
    return Ctx(repo=repo, gh=GitHubClient.connect(cfg.repo), db=open_db(root), cfg=cfg)
