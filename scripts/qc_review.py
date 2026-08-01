"""
Quality-control review agent.

This is deliberately a SEPARATE Claude call from whatever drafted the content -
same model, different job. The drafting agent's goal is to write something useful;
this agent's only goal is to find problems with what was written. Keeping these as
two separate calls (rather than one call doing both) matters: a single model
reviewing its own output in the same breath tends to rubber-stamp it, whereas a
fresh call with no investment in the draft looking good is a genuinely more
skeptical second opinion.

Any system that auto-sends anything (currently: generate_report.py) should run its
draft through qc_review() before deciding whether to send automatically. If QC
fails, treat it exactly like any other hold-for-review reason - do not send.
"""

import os
import json
import re
import requests

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]


def qc_review(draft_text, source_facts, contact_name, sender_name, content_type="client_email"):
    """
    draft_text: the generated content to check
    source_facts: dict of the real data the draft should be grounded in (so QC can
                  check for invented figures, not just style issues)
    content_type: "client_email" (default) - a one-way message sent to a named
                  contact, so the greeting/sign-off check applies.
                  "internal_briefing" or "social_caption" - content that never
                  has a greeting or sign-off by design (internal-only notes,
                  social captions), so that check is dropped entirely from the
                  prompt rather than softened - the model should never see a
                  rule it's meant to ignore.
    Returns: {"passed": bool, "issues": [str, ...]}
    """
    rules = [
        "Actual em dash (—) or en dash (–) characters anywhere. Standard hyphens (-), including when used with spaces around them as a sentence break (e.g. \"the site was fine - no issues\"), are completely acceptable and must NOT be flagged - only flag the literal — or – characters.",
        "Placeholder or template text left in (e.g. \"[Your name]\", \"Hi there\" instead of a real name, \"[Client Name]\", or similar).",
        "Any figure, statistic, date, or claim in the draft that does NOT appear in the source facts provided below (i.e. invented or hallucinated data).",
        "The draft asking the reader a question or inviting them to choose between options (this should be a one-way statement, not a conversation starter).",
    ]
    if content_type == "client_email":
        rules.append(f'The greeting not using "{contact_name}" or the sign-off not using "{sender_name}" correctly.')
    rules.append("Any tone that is overly salesy, uses corporate buzzwords, or doesn't match a plain, factual, warm-but-not-fluffy style.")
    rules.append("Any factual contradiction within the draft itself (e.g. saying uptime was perfect and also saying the site was down).")

    checks_text = "\n".join(f"{i}. {rule}" for i, rule in enumerate(rules, start=1))

    prompt = f"""You are a strict quality-control reviewer checking a piece of content before it is sent or published automatically, with no human reading it first. You did not write this content - your only job is to find problems with it. Be skeptical, not generous.

Check specifically for ALL of the following, and list every one that applies:

{checks_text}

Source facts (the ONLY data the draft is allowed to state as fact):
{json.dumps(source_facts, indent=2)}

Draft to review:
---
{draft_text}
---

First, think through each of the {len(rules)} checks in plain text. Work out what is and is not a genuine problem here. Take as long as you need.

Then, on a new line, output your conclusion as a single JSON object and nothing after it:
{{"passed": true or false, "issues": ["specific issue 1", "specific issue 2"]}}

If there are truly no issues, output {{"passed": true, "issues": []}}.

Rules for the issues array, follow these exactly:
- Only include things you concluded ARE genuine problems. If you considered something and decided it was acceptable, leave it out entirely.
- Each issue is one short statement under 25 words, stating only your conclusion.
- Never deliberate, hedge, or self-correct inside a string. All of that belongs in your plain text thinking above, not in the JSON.
- Name the specific text at fault in a few words so it can be found."""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()
    raw_text = "".join(block["text"] for block in data["content"] if block["type"] == "text")

    # The model reasons in plain text first, then emits the JSON object last,
    # so match the LAST balanced-looking object rather than the first.
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()
    matches = re.findall(r'\{[^{}]*"passed"[^{}]*\[[^\]]*\][^{}]*\}', cleaned, re.DOTALL)
    candidate = matches[-1] if matches else cleaned

    try:
        result = json.loads(candidate)
        return {"passed": bool(result.get("passed", False)), "issues": result.get("issues", [])}
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: any object at all
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group(0))
            return {"passed": bool(result.get("passed", False)), "issues": result.get("issues", [])}
        except (json.JSONDecodeError, AttributeError):
            pass

    # Truncation repair: salvage complete strings from the issues array only,
    # so plain-text reasoning above is not mistaken for findings.
    tail = cleaned.split('"issues"')[-1] if '"issues"' in cleaned else ""
    strings = re.findall(r'"((?:[^"\\]|\\.)*)"', tail)
    salvaged = [s for s in strings if len(s) > 30]
    if salvaged:
        return {
            "passed": False,
            "issues": [f"(recovered from an incomplete QC response) {s}" for s in salvaged[:5]],
        }

    return {"passed": False, "issues": [f"QC response could not be parsed - manual review required. Raw response: {raw_text[-200:]}"]}
