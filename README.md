# github-agent

A Claude agent that runs Git and GitHub for a two-person research team, so the researchers never type a git command. It keeps each person's branch synced, finds claims in one researcher's notes that contradict the other's, and drafts a pull request that cites both claims by file, line, author and commit.

It never merges on its own. A person approves every push, pull request, comment and merge, and the merge only goes through once the collaborator has approved the pull request on GitHub.

## Why it exists

Two researchers sharing notes, papers and diagrams on GitHub hit the same problems: one forgets to pull, branches drift, and a finding on one branch quietly contradicts a finding on the other. Git can show which lines changed. It cannot tell you that two paragraphs disagree. That judgement is what the model is for; everything else stays in plain, predictable git.

## How it splits the work

| Part | Who does it | Why |
|---|---|---|
| Fetch, commit, rebase, push, open PR, merge | Git and the GitHub API (deterministic code) | These must behave the same way every time |
| Extract claims from notes, spot contradictions, write the PR description | Claude (judgement) | Reading meaning is what code cannot do |
| Push, open a PR, comment, set a status, merge | A person (confirmation in the terminal) | Nothing leaves the machine without consent |
| Merge into `main` | The collaborator (approving review on GitHub) | Branch protection makes their approval the gate |

## The agent loop

`sync`, `merge` and `watch` run a sense, plan, act, observe, reflect loop:

1. **Sense:** snapshot the repo, both branches and any open pull request.
2. **Plan:** Claude proposes the next actions toward the goal, each with a reason.
3. **Act:** every action passes through the policy gate before it runs.
4. **Observe:** record what actually happened.
5. **Reflect:** Claude compares before and after and decides whether the goal is met or another step is needed (capped by `--max-steps`).

## The policy gate

`src/github_agent/policy.py` decides every action with three outcomes, in code, not in the prompt:

- **Auto:** fetch, extract, reconcile, commit, pull with rebase, on your own branch only.
- **Ask:** push, open a pull request, comment, set a commit status, merge, revert.
- **Deny:** anything containing "force", and any automatic action while on `main`.

The model can propose anything. It cannot run what the gate does not allow.

## Commands

```
github-agent init --repo owner/name --mine <your-branch> --theirs <their-branch>
github-agent reconcile          # dry run: conflict report and PR draft, touches nothing
github-agent pr                 # reconcile, then (after you confirm) push and open the PR
github-agent sync               # agent loop: keep my branch committed and rebased
github-agent merge              # agent loop: merge my PR only if the collaborator approved
github-agent watch --interval 60
github-agent history <path>     # who changed a file, and when
github-agent blame <path>       # per-line author, also for docx and pdf via text sidecars
github-agent revert <sha>       # undo a commit as a new commit; history is kept
```

## Setup

Requires Python 3.11+, git, and the GitHub CLI or a token.

```
pip install -e ".[dev]"
echo "ANTHROPIC_API_KEY=..." > .env       # GITHUB_TOKEN is optional; falls back to `gh auth token`
github-agent init --repo owner/name --mine alice/research --theirs bob/research
```

Then add a branch protection rule on `main` that requires one approving review. That rule is what turns the collaborator's review into consent.

Paths listed in `.github-agentignore` (gitignore syntax) are never sent to the model. Word and PDF files get a committed markdown copy so they can be compared and blamed line by line.

## Tests

```
pytest            # 129 tests, no network
pytest -m live    # 3 tests against the real Claude API (needs ANTHROPIC_API_KEY)
```

Also run end to end against a real GitHub repository: real reconcile, a real pull request with a conflict comment and a pending status, and `merge` refusing before the collaborator approved.

## Status

Working MVP for two people, one long-lived branch each. Design notes and decisions are in `tasks/todo.md`.
