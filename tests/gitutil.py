import os
import subprocess
from pathlib import Path


def run(cwd, *args, author: str = "Alice") -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": f"{author.lower()}@x.test",
        "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": f"{author.lower()}@x.test",
    }
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


def commit_file(work, path: str, text: str | bytes, msg: str, author: str = "Alice") -> None:
    p = Path(work) / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text) if isinstance(text, bytes) else p.write_text(text)
    run(work, "git", "add", path)
    run(work, "git", "commit", "-m", msg, author=author)
