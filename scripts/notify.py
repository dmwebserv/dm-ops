import json
import os
import requests

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO = os.environ["GITHUB_REPOSITORY"]  # auto-provided by Actions

def main():
    with open('logs/latest.json') as f:
        results = json.load(f)

    flagged = [r for r in results if r["status"] != "ok"]
    if not flagged:
        print("All sites OK - no issue created.")
        return

    urgent = [r for r in flagged if r["status"] == "urgent"]
    title = f"{'🔴 URGENT' if urgent else '🟡 Review needed'}: site check flagged {len(flagged)} issue(s)"

    body_lines = []
    for r in flagged:
        body_lines.append(f"### {r['name']} ({r['status'].upper()})")
        for e in r["errors"]:
            body_lines.append(f"- {e}")
        if r["broken_links"]:
            body_lines.append(f"  Broken links: {', '.join(l['url'] for l in r['broken_links'][:5])}")
        body_lines.append("")

    body = "\n".join(body_lines)

    resp = requests.post(
        f"https://api.github.com/repos/{REPO}/issues",
        headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
        json={"title": title, "body": body, "labels": ["site-check"]}
    )
    resp.raise_for_status()
    print(f"Issue created: {resp.json()['html_url']}")

if __name__ == "__main__":
    main()
