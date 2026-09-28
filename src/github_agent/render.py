from .models import Claim, ReconcileOutput


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def render_conflict_comment(out: ReconcileOutput, claims: dict[str, Claim]) -> str:
    rows = []
    for c in out.conflicts:
        cites = "<br>".join(
            f"`{claims[i].source_path}:{claims[i].line_start}` {claims[i].author} @ {claims[i].commit}"
            for i in c.claim_ids if i in claims
        )
        rows.append(
            f"| {c.severity.upper()} | {c.kind} | {_cell(c.explanation)} | {cites} | {_cell(c.suggested_resolution)} |"
        )
    table = (
        "| Severity | Kind | Why | Claims | Suggested resolution |\n|---|---|---|---|---|\n" + "\n".join(rows)
        if rows else "No conflicts found."
    )
    asks = "\n".join(f"- [ ] {q}" for q in out.pr.consent_questions)
    return (
        f"### github-agent: conflict report\nRecommendation: **{out.recommendation}** (advice only)\n\n{table}\n\n"
        f"### Consent requested\n{asks}\n\nApprove this PR to give consent. Request changes to object."
    )
