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


def qc_review(draft_text, source_facts, contact_name, sender_name):
    """
    draft_text: the generated content to check
    source_facts: dict of the real data the draft should be grounded in (so QC can
                  check for invented figures, not just style issues)
    Returns: {"passed": bool, "issues": [str, ...]}
    """
    prompt = f"""You are a strict quality-control reviewer checking a piece of client-facing content before it is sent automatically, with no human reading it first. You did not write this content - your only job is to find problems with it. Be skeptical, not generous.

Check specifically for ALL of the following, and list every one that applies:

1. Actual em dash (—) or en dash (–) characters anywhere. Standard hyphens (-), including when used with spaces around them as a sentence break (e.g. "the site was fine - no issues"), are completely acceptable and must NOT be flagged - only flag the literal — or – characters.
2. Placeholder or template text left in (e.g. "[Your name]", "Hi there" instead of a real name, "[Client Name]", or similar).
3. Any figure, statistic, date, or claim in the draft that does NOT appear in the source facts provided below (i.e. invented or hallucinated data).
4. The draft asking the reader a question or inviting them to choose between options (this should be a one-way statement, not a conversation starter).
5. The greeting not using "{contact_name}" or the sign-off not using "{sender_name}" correctly.
6. Any tone that is overly salesy, uses corporate buzzwords, or doesn't match a plain, factual, warm-but-not-fluffy style.
7. Any factual contradiction within the draft itself (e.g. saying uptime was perfect and also saying the site was down).

Source facts (the ONLY data the draft is allowed to state as fact):
{json.dumps(source_facts, indent=2)}

Draft to review:
---
{draft_text}
---

Respond with ONLY valid JSON, no other text, no markdown code fences, in this exact shape:
{{"passed": true or false, "issues": ["specific issue 1", "specific issue 2"]}}

If there are truly no issues, return {{"passed": true, "issues": []}}.

Rules for the issues array, follow these exactly:
- Each issue must be a single short statement under 25 words. State the problem plainly.
- Do NOT reason, deliberate, or correct yourself inside a string. Decide first, then write only your conclusion. Never write phrases like "wait", "checking", "however, on reflection".
- If you consider something and decide it is NOT a problem, simply leave it out. Do not mention it.
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
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()
    raw_text = "".join(block["text"] for block in data["content"] if block["type"] == "text")

    # Defensive parsing. Strip code fences, then isolate the JSON object rather
    # than assuming the whole response is clean JSON.
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    candidate = match.group(0) if match else cleaned

    try:
        result = json.loads(candidate)
        return {"passed": bool(result.get("passed", False)), "issues": result.get("issues", [])}
    except (json.JSONDecodeError, AttributeError):
        pass

    # Truncation repair: if the response was cut off mid-array, salvage the
    # complete strings we did receive rather than discarding a real review.
    strings = re.findall(r'"((?:[^"\\]|\\.)*)"', cleaned)
    salvaged = [s for s in strings if len(s) > 30 and s not in ("passed", "issues")]
    if salvaged:
        return {
            "passed": False,
            "issues": [f"(recovered from an incomplete QC response) {s}" for s in salvaged[:5]],
        }

    # Nothing usable. Fail safe: treat as a failed check rather than silently
    # letting content through unreviewed.
    return {"passed": False, "issues": [f"QC response could not be parsed - manual review required. Raw response: {raw_text[:200]}"]}
