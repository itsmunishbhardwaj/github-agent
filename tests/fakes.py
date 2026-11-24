from types import SimpleNamespace

from github_agent.github import PRComment, PRState


class FakeClaude:
    """Scripted stand-in for the network boundary: one parsed output per messages.parse call."""

    def __init__(self, *outputs):
        self.outputs, self.calls = list(outputs), []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        o = self.outputs.pop(0)
        return SimpleNamespace(parsed_output=o, content=[SimpleNamespace(type="text", text=o.model_dump_json())])


class FakePR:
    def __init__(self, number, author, reviews=(), issue_comments=(), url="https://github.test/pr/1"):
        self.number, self.user, self.html_url = number, SimpleNamespace(login=author), url
        self._reviews, self._issue_comments = list(reviews), list(issue_comments)
        self.comments, self.merged_with = [], None

    def get_reviews(self):
        return self._reviews

    def get_issue_comments(self):
        return self._issue_comments

    def create_issue_comment(self, body):
        self.comments.append(body)
        self._issue_comments.append(issue_comment(self.user.login, body, "2026-01-01T00:00:00"))

    def merge(self, merge_method):
        self.merged_with = merge_method


def issue_comment(user: str, body: str, created_at: str):
    return SimpleNamespace(user=SimpleNamespace(login=user), body=body, created_at=SimpleNamespace(isoformat=lambda: created_at))


def review(user: str, state: str):
    return SimpleNamespace(user=SimpleNamespace(login=user), state=state)


class FakeCommit:
    def __init__(self):
        self.statuses = []

    def create_status(self, **kwargs):
        self.statuses.append(kwargs)


class FakeRepo:
    owner = SimpleNamespace(login="alice-gh")

    def __init__(self, prs=()):
        self.prs, self.commits, self.created, self.pull_query = list(prs), {}, [], None

    def get_pulls(self, state, head):
        self.pull_query = (state, head)
        return list(self.prs)

    def get_pull(self, number):
        return next(p for p in self.prs if p.number == number)

    def create_pull(self, title, body, head, base):
        self.created.append({"title": title, "body": body, "head": head, "base": base})
        pr = FakePR(100 + len(self.created), "alice-gh")
        self.prs.append(pr)
        return pr

    def get_commit(self, sha):
        return self.commits.setdefault(sha, FakeCommit())


class FakeGH:
    """Records what the CLI/loop asks GitHub to do. Returns real PRState/PRComment, matching GitHubClient's contract."""

    def __init__(self):
        self.calls = []
        self._prs = {}  # branch -> PRState
        self._comments = {}  # pr number -> list[PRComment]
        self._next_number = 7

    def pr_for_branch(self, branch):
        return self._prs.get(branch)

    def open_pr(self, head, base, draft):
        self.calls.append(("open_pr", head, base, draft.title))
        number = self._next_number
        self._next_number += 1
        self._prs[head] = PRState(number=number, url=f"https://github.test/pr/{number}", consent="pending")
        self._comments[number] = []
        return number

    def seed_comment(self, number, author, body, created_at):
        """Test helper: inject an external (collaborator) comment as if left on GitHub."""
        self._comments.setdefault(number, []).append(PRComment(author=author, body=body, created_at=created_at))

    def pr_comments(self, number, since=None):
        return [c for c in self._comments.get(number, []) if since is None or c.created_at > since]

    def comment(self, number, body):
        self.calls.append(("comment", number, body))

    def set_status(self, sha, state, description):
        self.calls.append(("set_status", sha, state, description))

    def merge(self, number):
        self.calls.append(("merge", number))
