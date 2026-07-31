import json
import os
import glob
import yaml
import requests
from datetime import datetime, timezone, timedelta

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DAYS_BACK = 30

def load_history_for_client(client_id, days_back=DAYS_BACK):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    records = []
    for path in sorted(glob.glob("logs/history/*.json")):
        date_str = os.path.basename(path).replace(".json", "")
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if file_date < cutoff:
            continue
        with open(path) as f:
            day_results = json.load(f)
        for r in day_results:
            if r["id"] == client_id:
                records.append(r)
    return records

def summarise(records):
    if not records:
        return None
    total = len(records)
    # Uptime = site was reachable and didn't 5xx. Broken links / SSL warnings /
    # missing-form flags are real issues but NOT downtime, so they must not
    # count against uptime.
    up_count = sum(
        1 for r in records
        if not any("unreachable" in e or "Server error" in e for e in r.get("errors", []))
    )
    uptime_pct = round((up_count / total) * 100, 1)

    response_times = [r["response_time_ms"] for r in records if r.get("response_time_ms")]
    avg_response = round(sum(response_times) / len(response_times)) if response_times else None

    all_errors = []
    for r in records:
        for e in r.get("errors", []):
            all_errors.append({"date": r["checked_at"][:10], "issue": e})

    ssl_values = [r["ssl_days_left"] for r in records if r.get("ssl_days_left") is not None]
    ssl_latest = ssl_values[-1] if ssl_values else None

    return {
        "checks_run": total,
        "uptime_pct": uptime_pct,
        "avg_response_ms": avg_response,
        "issues": all_errors,
        "ssl_days_left_latest": ssl_latest,
    }

def needs_human_review(summary):
    """Decide whether this report should be held for manual review instead of
    auto-sent. Default is to auto-send; only hold when something is genuinely
    unusual, since that's when a second pair of eyes actually adds value."""
    reasons = []
    if summary["checks_run"] < 0:
        reasons.append(f"only {summary['checks_run']} day(s) of data this period (thin sample)")
    if summary["uptime_pct"] < 99.0:
        reasons.append(f"uptime dropped to {summary['uptime_pct']}%")
    if summary["ssl_days_left_latest"] is not None and summary["ssl_days_left_latest"] < 14:
        reasons.append(f"SSL expires in {summary['ssl_days_left_latest']} days (urgent)")
    if len(summary["issues"]) >= 3:
        reasons.append(f"{len(summary['issues'])} issues flagged this period (higher than usual)")
    return reasons

def draft_report(client_name, contact_name, sender_name, summary, period_label):
    if summary["issues"]:
        issues_text = "\n".join(f"- {i['date']}: {i['issue']}" for i in summary["issues"])
    else:
        issues_text = "None recorded this period."

    prompt = f"""You are writing a short, plain-English monthly website health update for a small business client of a freelance web designer. The client is not technical. Be warm but factual, no fluff, no vague marketing language. Focus on business value, not jargon.

This is a one-way informational update, not a conversation — do not ask the client questions or invite them to choose between options; state what will happen next as a plain fact.

Greet the client as "{contact_name}" and sign off as "{sender_name}". Do not use placeholder text like "Hi there" or "[Your name]" — use the real names given.

Client business: {client_name}
Contact: {contact_name}
Sent by: {sender_name}
Period: {period_label}

Data:
- Automated checks run: {summary['checks_run']}
- Uptime: {summary['uptime_pct']}%
- Average page load response time: {summary['avg_response_ms']}ms
- SSL certificate valid for: {summary['ssl_days_left_latest']} more days
- Issues detected during this period:
{issues_text}

Write a short update (150-250 words) covering: what was monitored, what's working well, anything that needed attention (and whether it's been resolved or still needs a look, stated as fact not a question), and one sentence on what's next. Do not invent any figures not given above. If there were no issues, say so plainly and positively without over-claiming."""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 600,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    response.raise_for_status()
    data = response.json()
    return "".join(block["text"] for block in data["content"] if block["type"] == "text")

def send_email(to_email, to_name, from_email, from_name, subject, body_markdown):
    resend_key = os.environ.get("RESEND_API_KEY")
    if not resend_key:
        raise RuntimeError("RESEND_API_KEY not set — cannot auto-send.")

    html_body = body_markdown.replace("\n", "<br>")
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
        json={
            "from": f"{from_name} <{from_email}>",
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        },
    )
    resp.raise_for_status()
    return resp.json()

def main():
    with open("clients.yaml") as f:
        config = yaml.safe_load(f)
        clients = config["clients"]
        business = config.get("business", {})

    sender_name = business.get("sender_name", "Your web team")
    from_email = business.get("from_email", "")

    period_label = datetime.now(timezone.utc).strftime("%B %Y")
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")

    os.makedirs("reports", exist_ok=True)
    os.makedirs("reports/_review_queue", exist_ok=True)

    for client in clients:
        if not client.get("care_plan"):
            continue

        contact_name = client.get("contact_name") or client["name"]
        contact_email = client.get("contact_email")

        records = load_history_for_client(client["id"])
        summary = summarise(records)

        if not summary:
            print(f"No data yet for {client['name']} — skipping.")
            continue

        report_text = draft_report(client["name"], contact_name, sender_name, summary, period_label)
        hold_reasons = needs_human_review(summary)

        full_doc = (
            f"# {client['name']} — Website Health Update ({period_label})\n\n"
            f"{report_text}\n\n---\n"
            f"*Raw data: {summary['checks_run']} automated checks, "
            f"{summary['uptime_pct']}% uptime, {len(summary['issues'])} issue(s) logged.*\n"
        )

        client_dir = f"reports/{client['id']}"
        os.makedirs(client_dir, exist_ok=True)
        out_path = f"{client_dir}/{month_str}.md"
        with open(out_path, "w") as f:
            f.write(full_doc)

        if hold_reasons:
            flag_path = f"reports/_review_queue/{client['id']}-{month_str}.md"
            with open(flag_path, "w") as f:
                f.write(f"HOLD FOR REVIEW — reasons:\n" + "\n".join(f"- {r}" for r in hold_reasons))
                f.write(f"\n\nTo: {contact_email}\n\n{full_doc}")
            print(f"HELD for review ({', '.join(hold_reasons)}): {flag_path}")
            continue

        if not contact_email:
            print(f"No contact_email set for {client['name']} — cannot auto-send, holding.")
            continue

        send_email(
            to_email=contact_email,
            to_name=contact_name,
            from_email=from_email,
            from_name=sender_name,
            subject=f"{client['name']} — Website Health Update ({period_label})",
            body_markdown=full_doc,
        )
        print(f"Auto-sent to {contact_email}: {out_path}")

if __name__ == "__main__":
    main()
