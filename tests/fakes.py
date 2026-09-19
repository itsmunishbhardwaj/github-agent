from types import SimpleNamespace


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
    def __init__(self, number, author, reviews=(), url="https://github.test/pr/1"):
        self.number, self.user, self.html_url = number, SimpleNamespace(login=author), url
        self._reviews, self.comments, self.merged_with = list(reviews), [], None

    def get_reviews(self):
        return self._reviews

    def create_issue_comment(self, body):
        self.comments.append(body)

    def merge(self, merge_method):
        self.merged_with = merge_method


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
    """Records what the CLI asks GitHub to do."""

    def __init__(self):
        self.calls = []

    def open_pr(self, head, base, draft):
        self.calls.append(("open_pr", head, base, draft.title))
        return 7

    def comment(self, number, body):
        self.calls.append(("comment", number, body))

    def set_status(self, sha, state, description):
        self.calls.append(("set_status", sha, state, description))
