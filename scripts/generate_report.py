import json
import os
import glob
import yaml
import requests
from datetime import datetime, timezone, timedelta
from qc_review import qc_review
from anthropic_client import call_claude

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
    if summary["checks_run"] < 7:
        reasons.append(f"only {summary['checks_run']} day(s) of data this period (thin sample)")
    if summary["uptime_pct"] < 99.0:
        reasons.append(f"uptime dropped to {summary['uptime_pct']}%")
    if summary["ssl_days_left_latest"] is not None and summary["ssl_days_left_latest"] < 14:
        reasons.append(f"SSL expires in {summary['ssl_days_left_latest']} days (urgent)")
    if len(summary["issues"]) >= 3:
        reasons.append(f"{len(summary['issues'])} issues flagged this period (higher than usual)")
    return reasons

def draft_report(client_name, contact_name, sender_name, summary, period_label, model):
    if summary["issues"]:
        issues_text = "\n".join(f"- {i['date']}: {i['issue']}" for i in summary["issues"])
    else:
        issues_text = "None recorded this period."

    prompt = f"""You are writing a short, plain-English monthly website health update for a small business client of a freelance web designer. The client is not technical. Be warm but factual, no fluff, no vague marketing language. Focus on business value, not jargon.

This is a one-way informational update, not a conversation - do not ask the client questions or invite them to choose between options; state what will happen next as a plain fact.

Greet the client as "{contact_name}" and sign off as "{sender_name}". Do not use placeholder text like "Hi there" or "[Your name]" - use the real names given. Use standard hyphens (-) only, never em dashes or en dashes.

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

Write a short update (150-250 words) covering: what was monitored, what's working well, anything that needed attention, and one sentence on what's next. If there were no issues, say so plainly and positively without over-claiming.

Critical accuracy rules, these override tone:
- The data above is automated monitoring only. It records what was DETECTED. It contains no record of any repair work.
- Therefore never state or imply that an issue has been fixed, resolved, actioned, or taken care of. Say it "has been flagged" or "is being looked into", never that it is done.
- Never promise a specific future date, deadline, or completion time.
- Never state a calendar date that is not given above. If told a number of days, say the number of days, do not convert it into a month or date.
- Do not invent any figure not given above."""

    return call_claude(ANTHROPIC_API_KEY, model, prompt, 600)

def render_email_html(body_markdown, client_name, period_label, summary):
    import markdown as md
    content_html = md.markdown(body_markdown, extensions=["nl2br"])

    ssl_display = f"{summary['ssl_days_left_latest']}d" if summary['ssl_days_left_latest'] is not None else "-"
    speed_display = f"{summary['avg_response_ms']}ms" if summary['avg_response_ms'] is not None else "-"

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0; padding:0; background-color:#f4f4f4; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f4; padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:8px; overflow:hidden; max-width:600px;">
          <tr>
            <td style="background-color:#101513; height:6px; line-height:6px; font-size:0;">&nbsp;</td>
          </tr>
          <tr>
            <td style="padding:28px 32px 8px 32px;">
              <div style="color:#888888; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; margin-bottom:4px;">Website Health Update</div>
              <div style="color:#101513; font-size:20px; font-weight:600;">{client_name}</div>
              <div style="color:#888888; font-size:13px;">{period_label}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 32px 8px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="33%" align="center" style="background-color:#f9f9f9; border-radius:6px; padding:14px 8px;">
                    <div style="color:#101513; font-size:20px; font-weight:700;">{summary['uptime_pct']}%</div>
                    <div style="color:#888888; font-size:11px; text-transform:uppercase; letter-spacing:0.04em; margin-top:2px;">Uptime</div>
                  </td>
                  <td width="4%"></td>
                  <td width="33%" align="center" style="background-color:#f9f9f9; border-radius:6px; padding:14px 8px;">
                    <div style="color:#101513; font-size:20px; font-weight:700;">{speed_display}</div>
                    <div style="color:#888888; font-size:11px; text-transform:uppercase; letter-spacing:0.04em; margin-top:2px;">Avg Speed</div>
                  </td>
                  <td width="4%"></td>
                  <td width="33%" align="center" style="background-color:#f9f9f9; border-radius:6px; padding:14px 8px;">
                    <div style="color:#101513; font-size:20px; font-weight:700;">{ssl_display}</div>
                    <div style="color:#888888; font-size:11px; text-transform:uppercase; letter-spacing:0.04em; margin-top:2px;">SSL Left</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px 32px 32px; color:#1a1a1a; font-size:15px; line-height:1.6;">
              {content_html}
            </td>
          </tr>
          <tr>
            <td style="padding:18px 32px; background-color:#f9f9f9; color:#888888; font-size:12px; line-height:1.5; border-top:1px solid #eeeeee;">
              DM Web Services - dmwebservices.co.uk
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

def send_email(to_email, to_name, from_email, from_name, subject, body_markdown, client_name, period_label, summary):
    resend_key = os.environ.get("RESEND_API_KEY")
    if not resend_key:
        raise RuntimeError("RESEND_API_KEY not set - cannot auto-send.")

    html_body = render_email_html(body_markdown, client_name, period_label, summary)
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
    test_mode = business.get("test_mode", False)
    test_email = business.get("test_email", "")
    force_send_for_testing = business.get("force_send_for_testing", False)
    model = business.get("anthropic_model", "claude-sonnet-4-6")

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
            print(f"No data yet for {client['name']} - skipping.")
            continue

        report_text = draft_report(client["name"], contact_name, sender_name, summary, period_label, model)
        hold_reasons = [] if force_send_for_testing else needs_human_review(summary)

        full_doc = (
            f"# {client['name']} - Website Health Update ({period_label})\n\n"
            f"{report_text}\n\n---\n"
            f"*Raw data: {summary['checks_run']} automated check{'s' if summary['checks_run'] != 1 else ''}, "
            f"{summary['uptime_pct']}% uptime, {len(summary['issues'])} issue{'s' if len(summary['issues']) != 1 else ''} logged.*\n"
        )

        # Second opinion: an independent QC pass on the written content (em
        # dashes, placeholders, invented figures, tone) - separate from the
        # data-anomaly checks above. Always run it so you get the finding in
        # the logs either way; but only let it BLOCK sending outside of test
        # mode, so force_send_for_testing still shows you the real draft even
        # if QC has a concern about it (useful for debugging the draft itself).
        if not hold_reasons:
            qc_result = qc_review(
                draft_text=report_text,
                source_facts={
                    **summary,
                    "reporting_period": period_label,
                    "client_name": client["name"],
                    "contact_name": contact_name,
                    "sender_name": sender_name,
                },
                contact_name=contact_name,
                sender_name=sender_name,
                model=model,
            )
            if not qc_result["passed"]:
                print(f"QC flagged issues for {client['name']}: {qc_result['issues']}")
                if not force_send_for_testing:
                    hold_reasons = [f"QC check failed: {issue}" for issue in qc_result["issues"]]

        client_dir = f"reports/{client['id']}"
        os.makedirs(client_dir, exist_ok=True)
        out_path = f"{client_dir}/{month_str}.md"
        with open(out_path, "w") as f:
            f.write(full_doc)

        if hold_reasons:
            flag_path = f"reports/_review_queue/{client['id']}-{month_str}.md"
            with open(flag_path, "w") as f:
                f.write(f"HOLD FOR REVIEW - reasons:\n" + "\n".join(f"- {r}" for r in hold_reasons))
                f.write(f"\n\nTo: {contact_email}\n\n{full_doc}")
            print(f"HELD for review ({', '.join(hold_reasons)}): {flag_path}")
            continue

        send_to = test_email if test_mode else contact_email
        subject_prefix = "[TEST MODE] " if test_mode else ""

        if not send_to:
            print(f"No email address available for {client['name']} - cannot auto-send, holding.")
            continue

        send_email(
            to_email=send_to,
            to_name=contact_name,
            from_email=from_email,
            from_name=sender_name,
            subject=f"{subject_prefix}{client['name']} - Website Health Update ({period_label})",
            body_markdown=full_doc,
            client_name=client["name"],
            period_label=period_label,
            summary=summary,
        )
        print(f"{'TEST-sent' if test_mode else 'Auto-sent'} to {send_to}: {out_path}")

if __name__ == "__main__":
    main()
