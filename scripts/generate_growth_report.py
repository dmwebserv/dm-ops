import json
import os
import yaml
import requests
from datetime import datetime, timezone
from qc_review import qc_review

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

def load_latest_findings(client_id):
    with open("logs/seo/latest.json") as f:
        results = json.load(f)
    for r in results:
        if r["id"] == client_id:
            return r
    return None

def draft_growth_report(client_name, findings):
    if not findings:
        return None

    findings_text = "\n".join(
        f"- [{f['severity']}] ({f['area']}) {f['detail']}" for f in findings
    )

    prompt = f"""You are a website growth advisor writing a short, prioritised action list for a small business client. The client is not technical. Use plain English, standard hyphens only (never em dashes or en dashes), and focus on business impact, not jargon.

Client: {client_name}

Raw technical findings from an automated website scan (severity: high/medium/low):
{findings_text}

Task: pick the THREE actions most likely to improve this website's search visibility or user experience, ranked by impact. For each action, explain in one or two plain-English sentences why it matters for the business (e.g. more enquiries, better first impressions, easier to find on Google) - not technical jargon. Do not just list every finding; be selective, and skip anything trivial low-impact even if it's in the data. If there are genuinely fewer than three meaningful actions, only list the ones that matter. End with one encouraging closing sentence. Keep the whole thing under 220 words. Do not invent findings not present in the data."""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 700,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()
    return "".join(block["text"] for block in data["content"] if block["type"] == "text")

def main():
    with open("clients.yaml") as f:
        clients = yaml.safe_load(f)["clients"]

    period_label = datetime.now(timezone.utc).strftime("%B %Y")
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")

    os.makedirs("reports/_review_queue", exist_ok=True)

    for client in clients:
        if not client.get("care_plan"):
            continue

        findings_record = load_latest_findings(client["id"])
        if not findings_record or not findings_record.get("findings"):
            print(f"No SEO findings for {client['name']} - skipping (may already be clean).")
            continue

        report_text = draft_growth_report(client["name"], findings_record["findings"])
        if not report_text:
            continue

        full_doc = (
            f"# {client['name']} - Growth Opportunities ({period_label})\n\n"
            f"{report_text}\n\n---\n"
            f"*Based on {len(findings_record['findings'])} technical signal(s) detected on {findings_record['checked_at'][:10]}.*\n"
        )

        # These already always hold for review regardless, but running QC still
        # adds value: the review-queue note tells you exactly what to check
        # instead of you having to spot it yourself.
        qc_result = qc_review(
            draft_text=full_doc,
            source_facts={"findings": findings_record["findings"]},
            contact_name=client["name"],
            sender_name="Danny",
        )
        qc_note = ""
        if not qc_result["passed"]:
            qc_note = "QC flagged:\n" + "\n".join(f"- {i}" for i in qc_result["issues"]) + "\n\n"

        client_dir = f"reports/{client['id']}"
        os.makedirs(client_dir, exist_ok=True)
        out_path = f"{client_dir}/growth-{month_str}.md"
        with open(out_path, "w") as f:
            f.write(full_doc)

        flag_path = f"reports/_review_queue/{client['id']}-growth-{month_str}.md"
        with open(flag_path, "w") as f:
            f.write("HOLD FOR REVIEW - reason: Growth Agent reports are always human-reviewed for now.\n\n")
            f.write(qc_note)
            f.write(full_doc)

        print(f"Growth report ready for review: {out_path}")

if __name__ == "__main__":
    main()
