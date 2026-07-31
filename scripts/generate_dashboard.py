import yaml
import json
import os
import glob
import requests
from datetime import datetime, timezone, timedelta

CARE_PLAN_MONTHLY_VALUE = 30  # £/month, per business rules in clients.yaml pricing

def load_yaml_config():
    with open("clients.yaml") as f:
        return yaml.safe_load(f)

def load_json_safe(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def compute_revenue(clients):
    care_plan_clients = [c for c in clients if c.get("care_plan")]
    mrr = len(care_plan_clients) * CARE_PLAN_MONTHLY_VALUE
    return {
        "care_plan_clients": len(care_plan_clients),
        "total_clients": len(clients),
        "mrr": mrr,
    }

def compute_site_health(clients):
    latest = load_json_safe("logs/latest.json")
    if not latest:
        return None
    per_client = []
    for entry in latest:
        per_client.append({
            "name": entry["name"],
            "status": entry["status"],
            "uptime_ok": entry["status"] == "ok" or "unreachable" not in " ".join(entry.get("errors", [])),
            "ssl_days_left": entry.get("ssl_days_left"),
            "issue_count": len(entry.get("errors", [])),
        })
    healthy_count = sum(1 for c in per_client if c["status"] == "ok")
    return {
        "per_client": per_client,
        "healthy_count": healthy_count,
        "total_checked": len(per_client),
    }

def compute_history_stats(days_back=30):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    files = []
    for path in sorted(glob.glob("logs/history/*.json")):
        date_str = os.path.basename(path).replace(".json", "")
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if file_date >= cutoff:
            files.append(path)
    total_checks = 0
    total_up = 0
    for path in files:
        day_data = load_json_safe(path)
        if not day_data:
            continue
        for r in day_data:
            total_checks += 1
            if not any("unreachable" in e or "Server error" in e for e in r.get("errors", [])):
                total_up += 1
    uptime_pct = round((total_up / total_checks) * 100, 1) if total_checks else None
    return {
        "days_of_history": len(files),
        "total_checks_run": total_checks,
        "rolling_uptime_pct": uptime_pct,
    }

def compute_seo_opportunities(clients):
    latest = load_json_safe("logs/seo/latest.json")
    if not latest:
        return None
    per_client = []
    total_high = 0
    total_medium = 0
    total_low = 0
    for entry in latest:
        findings = entry.get("findings", [])
        high = sum(1 for f in findings if f["severity"] == "high")
        medium = sum(1 for f in findings if f["severity"] == "medium")
        low = sum(1 for f in findings if f["severity"] == "low")
        total_high += high
        total_medium += medium
        total_low += low
        per_client.append({"name": entry["name"], "high": high, "medium": medium, "low": low, "total": len(findings)})
    return {
        "per_client": per_client,
        "total_high": total_high,
        "total_medium": total_medium,
        "total_low": total_low,
    }

def count_review_queue():
    if not os.path.isdir("reports/_review_queue"):
        return 0
    return len([f for f in os.listdir("reports/_review_queue") if f.endswith(".md")])

def count_open_github_issues():
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/issues",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
            params={"state": "open", "labels": "site-check"},
            timeout=10,
        )
        resp.raise_for_status()
        return len(resp.json())
    except requests.exceptions.RequestException:
        return None

def render_dashboard_html(data):
    revenue = data["revenue"]
    health = data["health"]
    history = data["history"]
    seo = data["seo"]
    review_queue_count = data["review_queue_count"]
    open_issues = data["open_issues"]
    generated_at = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")

    client_rows = ""
    if health:
        for c in health["per_client"]:
            status_color = "#2e7d32" if c["status"] == "ok" else ("#c62828" if c["status"] == "urgent" else "#f9a825")
            ssl_text = f"{c['ssl_days_left']}d" if c["ssl_days_left"] is not None else "-"
            client_rows += f"""
            <tr>
              <td style="padding:10px 12px; border-bottom:1px solid #eee;">{c['name']}</td>
              <td style="padding:10px 12px; border-bottom:1px solid #eee;"><span style="color:{status_color}; font-weight:600;">{c['status']}</span></td>
              <td style="padding:10px 12px; border-bottom:1px solid #eee;">{ssl_text}</td>
              <td style="padding:10px 12px; border-bottom:1px solid #eee;">{c['issue_count']}</td>
            </tr>"""

    seo_rows = ""
    if seo:
        for c in seo["per_client"]:
            seo_rows += f"""
            <tr>
              <td style="padding:10px 12px; border-bottom:1px solid #eee;">{c['name']}</td>
              <td style="padding:10px 12px; border-bottom:1px solid #eee;">{c['high']}</td>
              <td style="padding:10px 12px; border-bottom:1px solid #eee;">{c['medium']}</td>
              <td style="padding:10px 12px; border-bottom:1px solid #eee;">{c['low']}</td>
            </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>DM Web Services - Business Dashboard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background:#f4f4f4; margin:0; padding:24px; color:#1a1a1a; }}
  .wrap {{ max-width:900px; margin:0 auto; }}
  .top {{ background:#101513; color:#fff; padding:24px 28px; border-radius:8px 8px 0 0; }}
  .top h1 {{ margin:0; font-size:20px; font-weight:600; }}
  .top .sub {{ color:#aaa; font-size:12px; margin-top:4px; }}
  .card {{ background:#fff; padding:28px; border-radius:0 0 8px 8px; margin-bottom:20px; }}
  .stats {{ display:flex; gap:12px; margin-bottom:24px; flex-wrap:wrap; }}
  .stat {{ background:#f9f9f9; border-radius:6px; padding:16px; flex:1; min-width:120px; text-align:center; }}
  .stat .num {{ font-size:24px; font-weight:700; color:#101513; }}
  .stat .label {{ font-size:11px; text-transform:uppercase; letter-spacing:0.04em; color:#888; margin-top:4px; }}
  h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:0.04em; color:#888; border-bottom:1px solid #eee; padding-bottom:8px; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th {{ text-align:left; padding:10px 12px; font-size:11px; text-transform:uppercase; letter-spacing:0.04em; color:#888; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <h1>DM Web Services - Business Dashboard</h1>
    <div class="sub">Generated {generated_at}</div>
  </div>
  <div class="card">
    <div class="stats">
      <div class="stat"><div class="num">£{revenue['mrr']}</div><div class="label">Monthly Recurring</div></div>
      <div class="stat"><div class="num">{revenue['total_clients']}</div><div class="label">Total Clients</div></div>
      <div class="stat"><div class="num">{revenue['care_plan_clients']}</div><div class="label">Care Plan Clients</div></div>
      <div class="stat"><div class="num">{history['rolling_uptime_pct'] if history and history['rolling_uptime_pct'] is not None else '-'}%</div><div class="label">30-Day Uptime</div></div>
      <div class="stat"><div class="num">{review_queue_count}</div><div class="label">Awaiting Review</div></div>
      <div class="stat"><div class="num">{open_issues if open_issues is not None else '-'}</div><div class="label">Open Alerts</div></div>
    </div>

    <h2>Website Health</h2>
    <table>
      <tr><th>Client</th><th>Status</th><th>SSL Left</th><th>Issues</th></tr>
      {client_rows if client_rows else '<tr><td style="padding:10px 12px;">No data yet.</td></tr>'}
    </table>

    <h2 style="margin-top:28px;">Growth Opportunities</h2>
    <table>
      <tr><th>Client</th><th>High</th><th>Medium</th><th>Low</th></tr>
      {seo_rows if seo_rows else '<tr><td style="padding:10px 12px;">No data yet.</td></tr>'}
    </table>

    <h2 style="margin-top:28px;">Automation Activity</h2>
    <table>
      <tr><td style="padding:10px 12px; border-bottom:1px solid #eee;">Days of monitoring history</td><td style="padding:10px 12px; border-bottom:1px solid #eee;">{history['days_of_history'] if history else '-'}</td></tr>
      <tr><td style="padding:10px 12px;">Total automated checks run</td><td style="padding:10px 12px;">{history['total_checks_run'] if history else '-'}</td></tr>
    </table>
  </div>
</div>
</body>
</html>"""

def main():
    config = load_yaml_config()
    clients = config["clients"]

    revenue = compute_revenue(clients)
    health = compute_site_health(clients)
    history = compute_history_stats()
    seo = compute_seo_opportunities(clients)
    review_queue_count = count_review_queue()
    open_issues = count_open_github_issues()

    data = {
        "revenue": revenue,
        "health": health,
        "history": history,
        "seo": seo,
        "review_queue_count": review_queue_count,
        "open_issues": open_issues,
    }

    os.makedirs("dashboard", exist_ok=True)
    with open("dashboard/index.html", "w") as f:
        f.write(render_dashboard_html(data))

    # Also save raw data as JSON, so it can be read programmatically (e.g. by
    # Claude in a future chat, or a future automation) without re-parsing HTML.
    with open("dashboard/data.json", "w") as f:
        json.dump(data, f, indent=2, default=str)

    print("Dashboard generated: dashboard/index.html")
    print(json.dumps(data, indent=2, default=str))

if __name__ == "__main__":
    main()
