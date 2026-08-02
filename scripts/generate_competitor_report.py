"""
Competitor intelligence - internal briefing.

Reads the diff produced by competitor_check.py and, if anything genuinely
changed, drafts a single internal briefing about DM Web Services' own
competitive market. Competitors belong to the business, not to any one
client, so this is one document, not one per client.

Two deliberate constraints:

1. This is internal. The output is for Danny, never for a client, and it is
   never emailed. It always lands in reports/_review_queue/ regardless of what
   QC thinks, because a competitor briefing is a judgement input, not a routine
   notification - the autonomous-by-default rule doesn't apply to something
   whose only consumer is a human decision.

2. Silence is a valid result. A month where a competitor tweaked their footer
   is a month with nothing to report, and the drafting prompt says so
   explicitly. A briefing that manufactures significance out of noise is worse
   than no briefing, because it trains you to stop reading them.

No competitors configured under business.competitors produces nothing at all.
"""

import json
import os
import yaml
from datetime import datetime, timezone
from qc_review import qc_review
from anthropic_client import call_claude

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

LATEST_PATH = "logs/competitors/latest.json"
REVIEW_QUEUE_DIR = "reports/_review_queue"
ARCHIVE_DIR = "reports/_business"


def changed_competitors(latest):
    """Only competitors with a real, non-empty diff. Baselines, unchanged
    pages, and fetch errors are not something to write a briefing about."""
    return [
        c for c in latest.get("competitors", [])
        if c.get("status") == "changed" and (c.get("added") or c.get("removed"))
    ]


def format_changes(competitors):
    blocks = []
    for comp in competitors:
        added = comp.get("added") or []
        removed = comp.get("removed") or []
        lines = [f"Competitor: {comp['name']} ({comp['url']})"]
        lines.append(f"Compared against the snapshot taken on {comp.get('compared_to')}.")
        if comp.get("truncated"):
            lines.append(
                f"Note: {comp.get('added_count')} lines were added and {comp.get('removed_count')} "
                f"removed in total; only {len(added)} added and {len(removed)} removed are listed here."
            )
        lines.append("New or changed text now on the page:")
        lines.extend([f"  + {line}" for line in added] or ["  (none)"])
        lines.append("Text that was on the page before and is now gone:")
        lines.extend([f"  - {line}" for line in removed] or ["  (none)"])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def draft_briefing(sender_name, period_label, competitors, model):
    changes_text = format_changes(competitors)

    prompt = f"""You are writing a short internal briefing for {sender_name}, a solo freelance web developer, about what their own competitors - other web design studios and agencies in their market - have changed on their websites this month. Nobody but {sender_name} will read it. It is not a client-facing document and it is not a sales pitch.

Period: {period_label}

Below is an automated line-level diff of each competitor's website: text that appeared since the last snapshot, and text that disappeared. It is raw and noisy. Website diffs pick up rewording, reordering, seasonal copy, and template changes that mean nothing commercially.

{changes_text}

Your job is to report ONLY changes with genuine commercial meaning, which means one of:
- a new service, product, or service area they did not offer before
- a pricing change, a new package, or prices being published or removed
- a new accreditation, certification, award, insurance, or trade body membership
- a clear repositioning (different target customer, different specialism, different core message)

Everything else is noise. Rewording, layout changes, new photos, blog posts, testimonials, updated phone numbers, seasonal messaging, and general copy polish are all noise. Do not report them.

Critical instruction, this matters more than being useful: if the diff contains nothing that meets the bar above, say so plainly in one or two sentences and stop. Saying "nothing significant this month" is a correct and valuable answer. Do not stretch, speculate about, or inflate a minor change to have something to report. Do not guess at a competitor's motive or strategy beyond what the text on their page actually states.

Style rules:
- Plain English, factual, brief. No marketing language, no buzzwords, no filler.
- Use standard hyphens (-) only. Never use em dashes or en dashes.
- State only what the diff shows. Never invent a figure, price, date, or claim that is not in the text above.
- No greeting and no sign-off. Start straight into the briefing.
- If you do have something to report, keep it under 200 words: what changed, on whose site, and one plain sentence on why it might matter for DM Web Services. Do not recommend a course of action.
- Do not ask any questions."""

    return call_claude(ANTHROPIC_API_KEY, model, prompt, 700)


def main():
    with open("clients.yaml") as f:
        business = yaml.safe_load(f).get("business", {})

    sender_name = business.get("sender_name", "Your web team")
    model = business.get("anthropic_model", "claude-sonnet-4-6")

    if not business.get("competitors"):
        print("No competitors configured in clients.yaml - nothing to report.")
        return

    if not os.path.exists(LATEST_PATH):
        print(f"{LATEST_PATH} not found - run competitor_check.py first.")
        return

    with open(LATEST_PATH) as f:
        latest = json.load(f)

    now = datetime.now(timezone.utc)
    month_str = now.strftime("%Y-%m")
    period_label = now.strftime("%B %Y")

    competitors = changed_competitors(latest)
    if not competitors:
        print("No competitor changes detected - no briefing.")
        return

    briefing = draft_briefing(sender_name, period_label, competitors, model)

    checked_names = ", ".join(c["name"] for c in competitors)
    full_doc = (
        f"# Competitor Briefing ({period_label})\n\n"
        f"{briefing}\n\n---\n"
        f"*Internal note, never sent to anyone. Based on an automated website diff of: "
        f"{checked_names}. Snapshot date {latest.get('date')}.*\n"
    )

    # QC is a second opinion on the writing (invented figures, dashes,
    # tone), not a gate here - nothing is sent either way, so a flag is
    # recorded as a note on top of the draft rather than blocking it.
    # Only the drafted prose goes to QC - the heading and footer above are
    # deterministic wrapper text this script controls, not AI output, so
    # there's nothing for QC to check them against.
    qc_result = qc_review(
        draft_text=briefing,
        source_facts={
            "reporting_period": period_label,
            "sender_name": sender_name,
            "snapshot_date": latest.get("date"),
            "competitor_changes": competitors,
        },
        contact_name=sender_name,
        sender_name=sender_name,
        content_type="internal_briefing",
        model=model,
    )
    qc_note = ""
    if not qc_result["passed"]:
        qc_note = "QC flagged:\n" + "\n".join(f"- {i}" for i in qc_result["issues"]) + "\n\n"
        print(f"QC flagged issues: {qc_result['issues']}")

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(f"{ARCHIVE_DIR}/competitors-{month_str}.md", "w") as f:
        f.write(full_doc)

    os.makedirs(REVIEW_QUEUE_DIR, exist_ok=True)
    out_path = f"{REVIEW_QUEUE_DIR}/business-competitors-{month_str}.md"
    with open(out_path, "w") as f:
        f.write(
            "HOLD FOR REVIEW - reason: internal competitor briefing, "
            "for your eyes only and never sent to anyone.\n\n"
        )
        f.write(qc_note)
        f.write(full_doc)

    print(f"Competitor briefing ready for review: {out_path}")


if __name__ == "__main__":
    main()
