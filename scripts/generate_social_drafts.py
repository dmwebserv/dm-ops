import yaml
import requests
import re
import os
import json
from datetime import datetime, timezone

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

def fetch_site_text(url):
    try:
        r = requests.get(url, timeout=15)
        if r.status_code >= 400:
            return None
        html = r.text
        # Strip script/style, then tags, to get readable content only
        text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:4000]  # cap length, homepage content is enough signal
    except requests.exceptions.RequestException:
        return None

def draft_social_posts(client_name, site_text):
    if not site_text:
        return None

    prompt = f"""You are drafting social media post ideas for a small local business, based on their own website content. Use plain English, standard hyphens only (never em dashes or en dashes), and avoid generic AI-sounding phrasing (no "elevate", "unlock", "in today's world", excessive exclamation marks, or corporate buzzwords).

Business: {client_name}
Website content (raw extract, may include navigation text - use judgement on what's genuinely postable content vs boilerplate):
{site_text}

Task: draft 3 short social media post captions (Instagram/Facebook style, roughly 2-4 sentences each) that a real tradesperson or small business owner could post, based on what's actually on their site. Ground every post in something specific from the content given - do not invent services, reviews, or details not present. Each post should have a different angle (e.g. one about a specific service, one building trust/credibility, one with a clear call to action). Note after each post what kind of photo would suit it (one line, practical - e.g. "a finished job photo" or "a before/after shot"), since these need pairing with real photos before posting - do not invent that a photo exists.

Format as:
**Post 1: [angle]**
[caption]
Suggested image: [description]

(repeat for posts 2 and 3)"""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 900,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()
    return "".join(block["text"] for block in data["content"] if block["type"] == "text")

def main():
    with open("clients.yaml") as f:
        clients = yaml.safe_load(f)["clients"]

    month_str = datetime.now(timezone.utc).strftime("%Y-%m")
    period_label = datetime.now(timezone.utc).strftime("%B %Y")

    os.makedirs("reports/_review_queue", exist_ok=True)

    for client in clients:
        if not client.get("care_plan"):
            continue

        site_text = fetch_site_text(client["url"])
        if not site_text:
            print(f"Could not fetch site content for {client['name']} - skipping.")
            continue

        drafts = draft_social_posts(client["name"], site_text)
        if not drafts:
            continue

        full_doc = (
            f"# {client['name']} - Social Post Drafts ({period_label})\n\n"
            f"{drafts}\n\n---\n"
            f"*Drafted from current website content. Pair with real photos before posting - "
            f"do not post without reviewing and adding actual images.*\n"
        )

        client_dir = f"reports/{client['id']}"
        os.makedirs(client_dir, exist_ok=True)
        out_path = f"{client_dir}/social-{month_str}.md"
        with open(out_path, "w") as f:
            f.write(full_doc)

        # Always held for review - these are drafts for you to pair with real photos
        # and post yourself, never auto-posted anywhere.
        flag_path = f"reports/_review_queue/{client['id']}-social-{month_str}.md"
        with open(flag_path, "w") as f:
            f.write("HOLD FOR REVIEW - reason: social drafts always need a human pass (photo pairing, tone check) before posting.\n\n")
            f.write(full_doc)

        print(f"Social drafts ready for review: {out_path}")

if __name__ == "__main__":
    main()
