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
    ok_count = sum(1 for r in records if r["status"] == "ok")
    uptime_pct = round((ok_count / total) * 100, 1)

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

def draft_report(client_name, summary, period_label):
    if summary["issues"]:
        issues_text = "\n".join(f"- {i['date']}: {i['issue']}" for i in summary["issues"])
    else:
        issues_text = "None recorded this period."

    prompt = f"""You are writing a short, plain-English monthly website health update for a small business client of a freelance web designer. The client is not technical. Be warm but factual, no fluff, no vague marketing language. Focus on business value, not jargon.

Client: {client_name}
Period: {period_label}

Data:
- Automated checks run: {summary['checks_run']}
- Uptime: {summary['uptime_pct']}%
- Average page load response time: {summary['avg_response_ms']}ms
- SSL certificate valid for: {summary['ssl_days_left_latest']} more days
- Issues detected during this period:
{issues_text}

Write a short update (150-250 words) covering: what was monitored, what's working well, anything that needed attention (and whether it's been resolved or still needs a look), and one sentence on what's next. Do not invent any figures not given above. If there were no issues, say so plainly and positively without over-claiming."""

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

def main():
    with open("clients.yaml") as f:
        clients = yaml.safe_load(f)["clients"]

    period_label = datetime.now(timezone.utc).strftime("%B %Y")
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")

    os.makedirs("reports", exist_ok=True)

    for client in clients:
        if not client.get("care_plan"):
            continue  # only generate for Care Plan clients

        records = load_history_for_client(client["id"])
        summary = summarise(records)

        if not summary:
            print(f"No data yet for {client['name']} — skipping.")
            continue

        report_text = draft_report(client["name"], summary, period_label)

        client_dir = f"reports/{client['id']}"
        os.makedirs(client_dir, exist_ok=True)
        out_path = f"{client_dir}/{month_str}.md"
        with open(out_path, "w") as f:
            f.write(f"# {client['name']} — Website Health Update ({period_label})\n\n")
            f.write(report_text)
            f.write(f"\n\n---\n*Raw data: {summary['checks_run']} automated checks, "
                     f"{summary['uptime_pct']}% uptime, {len(summary['issues'])} issue(s) logged.*\n")

        print(f"Report written: {out_path}")

if __name__ == "__main__":
    main()
