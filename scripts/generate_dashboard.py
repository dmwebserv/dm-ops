import yaml
import json
import os
import glob
import re
import requests
from datetime import datetime, timezone, timedelta

CARE_PLAN_MONTHLY_VALUE = 30

# Every system in the estate. Keyed by workflow filename so we can match against
# the GitHub Actions API and report real last-run state rather than assuming.
SYSTEMS = [
    {"key": "site-checks.yml", "name": "Site Checks", "cadence": "Daily", "job": "Uptime, SSL, links, forms"},
    {"key": "monthly-report.yml", "name": "Client Reports", "cadence": "Monthly", "job": "Health update, auto-sent"},
    {"key": "seo-checks.yml", "name": "SEO Scan", "cadence": "Weekly", "job": "On-page technical signals"},
    {"key": "growth-report.yml", "name": "Growth Report", "cadence": "Monthly", "job": "Top 3 actions per client"},
    {"key": "social-drafts.yml", "name": "Social Drafts", "cadence": "Monthly", "job": "Post captions from site content"},
    {"key": "competitor-intel.yml", "name": "Competitor Intel", "cadence": "Monthly", "job": "Rival site change briefing"},
    {"key": "dashboard.yml", "name": "This Dashboard", "cadence": "Weekly", "job": "Rebuilds this console"},
]


def load_json_safe(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None


def gh_api(path, params=None):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}{path}",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
            params=params or {},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException:
        return None


def get_workflow_runs():
    """Real last-run state per workflow. Returns {} if the API is unreachable,
    which the UI reports honestly rather than showing a false green."""
    workflows = gh_api("/actions/workflows")
    if not workflows:
        return {}

    out = {}
    for wf in workflows.get("workflows", []):
        filename = os.path.basename(wf.get("path", ""))
        runs = gh_api(f"/actions/workflows/{wf['id']}/runs", {"per_page": 1})
        if not runs or not runs.get("workflow_runs"):
            out[filename] = {"state": "never_run", "when": None, "url": wf.get("html_url")}
            continue
        run = runs["workflow_runs"][0]
        out[filename] = {
            "state": run.get("conclusion") or run.get("status") or "unknown",
            "when": run.get("updated_at"),
            "url": run.get("html_url"),
        }
    return out


def humanise_age(iso_string):
    if not iso_string:
        return "never"
    try:
        then = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    delta = datetime.now(timezone.utc) - then
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    return f"{days // 30}mo ago"


def compute_revenue(clients):
    care = [c for c in clients if c.get("care_plan")]
    return {"care_plan_clients": len(care), "total_clients": len(clients), "mrr": len(care) * CARE_PLAN_MONTHLY_VALUE}


def compute_health(clients):
    latest = load_json_safe("logs/latest.json") or []
    by_id = {e["id"]: e for e in latest}
    rows = []
    for c in clients:
        e = by_id.get(c["id"])
        if not e:
            rows.append({"id": c["id"], "name": c["name"], "url": c.get("url", ""), "status": "no_data",
                         "ssl_days_left": None, "response_ms": None, "errors": [], "checked_at": None})
            continue
        rows.append({
            "id": c["id"], "name": c["name"], "url": c.get("url", ""),
            "status": e.get("status", "unknown"),
            "ssl_days_left": e.get("ssl_days_left"),
            "response_ms": e.get("response_time_ms"),
            "errors": e.get("errors", []),
            "checked_at": e.get("checked_at"),
        })
    return rows


def compute_history(days_back=30):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    total = up = 0
    days = 0
    daily = []
    for path in sorted(glob.glob("logs/history/*.json")):
        name = os.path.basename(path).replace(".json", "")
        try:
            d = datetime.strptime(name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if d < cutoff:
            continue
        data = load_json_safe(path) or []
        days += 1
        day_total = day_up = 0
        for r in data:
            errs = " ".join(r.get("errors", []))
            total += 1
            day_total += 1
            if "unreachable" not in errs and "Server error" not in errs:
                up += 1
                day_up += 1
        if day_total:
            daily.append({"date": name, "pct": round(day_up / day_total * 100, 1)})
    return {
        "days": days,
        "checks": total,
        "uptime_pct": round(up / total * 100, 1) if total else None,
        "daily": daily[-30:],
    }


def compute_seo(clients):
    latest = load_json_safe("logs/seo/latest.json")
    if not latest:
        return None
    by_id = {e["id"]: e for e in latest}
    rows = []
    for c in clients:
        e = by_id.get(c["id"])
        if not e:
            continue
        f = e.get("findings", [])
        rows.append({
            "id": c["id"], "name": c["name"],
            "high": [x for x in f if x["severity"] == "high"],
            "medium": [x for x in f if x["severity"] == "medium"],
            "low": [x for x in f if x["severity"] == "low"],
            "total": len(f),
            "checked_at": e.get("checked_at"),
        })
    return rows


def compute_competitors(clients):
    latest = load_json_safe("logs/competitors/latest.json")
    configured = any(c.get("competitors") for c in clients)
    return {"configured": configured, "records": latest or []}


def read_review_queue():
    d = "reports/_review_queue"
    if not os.path.isdir(d):
        return []
    items = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(d, fn)
        try:
            with open(path, encoding="utf-8") as f:
                body = f.read()
        except OSError:
            body = ""
        reason = ""
        m = re.search(r"HOLD FOR REVIEW[^\n]*", body)
        if m:
            reason = m.group(0).replace("HOLD FOR REVIEW - reason:", "").replace("HOLD FOR REVIEW - reasons:", "").strip()
        kind = "Client report"
        if "-growth-" in fn:
            kind = "Growth report"
        elif "-social-" in fn:
            kind = "Social drafts"
        elif "-competitors-" in fn:
            kind = "Competitor brief"
        items.append({"file": fn, "kind": kind, "reason": reason or "Held for review", "body": body})
    return items


def read_config_flags(business):
    return {
        "test_mode": bool(business.get("test_mode")),
        "force_send": bool(business.get("force_send_for_testing")),
        "from_email": business.get("from_email", ""),
        "test_email": business.get("test_email", ""),
    }


def build_attention(health, seo, queue, flags, runs, competitors):
    """The single most important computation: what actually needs Danny."""
    items = []

    if flags["test_mode"] or flags["force_send"]:
        items.append({"weight": 0, "label": "Test mode is on - no reports are reaching real clients",
                      "detail": "Set test_mode and force_send_for_testing to false in clients.yaml", "view": "systems"})

    for h in health:
        if h["status"] == "urgent":
            items.append({"weight": 1, "label": f"{h['name']} needs urgent attention",
                          "detail": "; ".join(h["errors"]) or "Flagged urgent", "view": "clients"})
        elif h["ssl_days_left"] is not None and h["ssl_days_left"] < 21:
            items.append({"weight": 2, "label": f"{h['name']} certificate expires in {h['ssl_days_left']} days",
                          "detail": "Renew before it lapses", "view": "clients"})

    for f, r in runs.items():
        if r["state"] in ("failure", "timed_out"):
            sysname = next((s["name"] for s in SYSTEMS if s["key"] == f), f)
            items.append({"weight": 1, "label": f"{sysname} failed on its last run",
                          "detail": "Open the run log to see why", "view": "systems"})

    if queue:
        items.append({"weight": 3, "label": f"{len(queue)} item{'s' if len(queue) != 1 else ''} waiting for you to read",
                      "detail": "Reports held back rather than sent automatically", "view": "queue"})

    if seo:
        high_total = sum(len(r["high"]) for r in seo)
        if high_total:
            items.append({"weight": 3, "label": f"{high_total} high-priority site issue{'s' if high_total != 1 else ''} found",
                          "detail": "Worth fixing - these affect search visibility", "view": "growth"})

    items.sort(key=lambda x: x["weight"])
    return items


# ---------------------------------------------------------------------------
# Rendering. CSS kept out of f-strings to avoid brace escaping mistakes.
# ---------------------------------------------------------------------------

CSS = """
:root{
  --base:#101513; --raised:#171E1A; --sunk:#0B100E; --line:#242D28;
  --ink:#E6EDE8; --ink-dim:#8A9890; --ink-faint:#5D6A63;
  --live:#6FA88A; --warn:#D4A24C; --stop:#B4544A; --idle:#3E4A44;
}
*{box-sizing:border-box;margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{
  background:var(--base); color:var(--ink);
  font-family:'IBM Plex Sans',ui-sans-serif,system-ui,-apple-system,sans-serif;
  font-size:15px; line-height:1.55; min-height:100vh;
}
.mono{font-family:'IBM Plex Mono',ui-monospace,'SF Mono',Menlo,monospace}
.shell{display:flex; min-height:100vh}

/* Rail */
.rail{
  width:216px; flex:0 0 216px; background:var(--sunk);
  border-right:1px solid var(--line); padding:26px 0; position:sticky; top:0; height:100vh;
  display:flex; flex-direction:column;
}
.brand{padding:0 22px 26px; border-bottom:1px solid var(--line); margin-bottom:18px}
.brand .mark{
  font-family:'Space Grotesk',ui-sans-serif,sans-serif; font-size:19px; font-weight:600;
  letter-spacing:-0.02em; color:var(--ink);
}
.brand .sub{font-size:11px; color:var(--ink-faint); letter-spacing:0.1em; text-transform:uppercase; margin-top:3px}
.navlink{
  display:flex; align-items:center; gap:11px; width:100%; text-align:left;
  padding:10px 22px; background:none; border:0; cursor:pointer; color:var(--ink-dim);
  font-family:inherit; font-size:14px; border-left:2px solid transparent;
}
.navlink:hover{color:var(--ink); background:rgba(255,255,255,0.02)}
.navlink.on{color:var(--ink); border-left-color:var(--live); background:rgba(111,168,138,0.07)}
.navlink .count{
  margin-left:auto; font-size:11px; padding:1px 7px; border-radius:9px;
  background:var(--line); color:var(--ink-dim); font-family:'IBM Plex Mono',monospace;
}
.navlink .count.hot{background:rgba(212,162,76,0.16); color:var(--warn)}
.rail-foot{margin-top:auto; padding:16px 22px 0; border-top:1px solid var(--line); font-size:11px; color:var(--ink-faint)}

/* Main */
.main{flex:1; min-width:0; padding:30px 34px 60px; max-width:1180px}
.view{display:none}
.view.on{display:block}

/* Verdict */
.verdict{
  border:1px solid var(--line); border-radius:9px; padding:20px 22px;
  background:var(--raised); margin-bottom:26px; display:flex; gap:16px; align-items:flex-start;
}
.verdict .dot{width:9px;height:9px;border-radius:50%;margin-top:7px;flex:0 0 9px}
.verdict h1{
  font-family:'Space Grotesk',sans-serif; font-size:21px; font-weight:500;
  letter-spacing:-0.015em; line-height:1.3;
}
.verdict p{color:var(--ink-dim); font-size:14px; margin-top:4px}
.verdict .stamp{margin-left:auto; text-align:right; font-size:11px; color:var(--ink-faint); white-space:nowrap}

/* Pulse strip */
.strip{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr));
  gap:1px; background:var(--line); border:1px solid var(--line);
  border-radius:9px; overflow:hidden; margin-bottom:28px;
}
.pulse{background:var(--raised); padding:16px 14px 14px; position:relative}
.pulse .bars{display:flex; align-items:flex-end; gap:3px; height:26px; margin-bottom:11px}
.pulse .bar{
  flex:1; background:var(--idle); border-radius:1px; transform-origin:bottom;
  animation:rise .5s cubic-bezier(.2,.8,.3,1) backwards;
}
@keyframes rise{from{transform:scaleY(.15);opacity:.3}to{transform:scaleY(1);opacity:1}}
.pulse .nm{font-size:13px; font-weight:500; letter-spacing:-0.01em}
.pulse .mt{font-size:11px; color:var(--ink-faint); margin-top:2px}
.pulse .cad{
  position:absolute; top:14px; right:14px; font-size:9px; letter-spacing:0.09em;
  text-transform:uppercase; color:var(--ink-faint);
}
.pulse a{position:absolute; inset:0; text-decoration:none}

/* Sections + cards */
.eyebrow{
  font-size:10px; letter-spacing:0.14em; text-transform:uppercase;
  color:var(--ink-faint); margin:32px 0 12px; display:flex; align-items:center; gap:10px;
}
.eyebrow:after{content:''; flex:1; height:1px; background:var(--line)}
.eyebrow:first-child{margin-top:0}
.grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(268px,1fr)); gap:14px}
.card{background:var(--raised); border:1px solid var(--line); border-radius:9px; padding:18px 20px}
.card h3{font-size:15px; font-weight:500; letter-spacing:-0.01em; display:flex; align-items:center; gap:9px}
.card .link{font-size:12px; color:var(--ink-faint); text-decoration:none; word-break:break-all}
.card .link:hover{color:var(--live)}
.metrics{display:flex; gap:22px; margin-top:15px; flex-wrap:wrap}
.metric .v{font-family:'IBM Plex Mono',monospace; font-size:19px; letter-spacing:-0.02em}
.metric .k{font-size:10px; letter-spacing:0.1em; text-transform:uppercase; color:var(--ink-faint); margin-top:1px}
.pip{width:7px;height:7px;border-radius:50%;flex:0 0 7px}
.tag{
  display:inline-block; font-size:10px; letter-spacing:0.07em; text-transform:uppercase;
  padding:2px 7px; border-radius:3px; border:1px solid var(--line); color:var(--ink-dim);
}

/* Numbers row */
.figures{display:grid; grid-template-columns:repeat(auto-fit,minmax(118px,1fr)); gap:14px; margin-bottom:6px}
.fig{background:var(--raised); border:1px solid var(--line); border-radius:9px; padding:16px 18px}
.fig .v{font-family:'IBM Plex Mono',monospace; font-size:25px; letter-spacing:-0.03em; line-height:1}
.fig .k{font-size:10px; letter-spacing:0.11em; text-transform:uppercase; color:var(--ink-faint); margin-top:7px}

/* Attention list */
.att{border:1px solid var(--line); border-radius:9px; overflow:hidden}
.att-row{
  display:flex; gap:13px; align-items:flex-start; padding:14px 18px;
  background:var(--raised); border-bottom:1px solid var(--line); cursor:pointer; width:100%;
  text-align:left; border-left:0; border-right:0; border-top:0; font-family:inherit; color:inherit;
}
.att-row:last-child{border-bottom:0}
.att-row:hover{background:#1B231E}
.att-row .t{font-size:14px}
.att-row .d{font-size:12.5px; color:var(--ink-dim); margin-top:2px}
.att-row .go{margin-left:auto; color:var(--ink-faint); font-size:16px; line-height:1}

/* Queue */
.q-item{background:var(--raised); border:1px solid var(--line); border-radius:9px; margin-bottom:12px; overflow:hidden}
.q-head{
  display:flex; gap:12px; align-items:center; padding:15px 18px; cursor:pointer;
  width:100%; background:none; border:0; font-family:inherit; color:inherit; text-align:left;
}
.q-head:hover{background:#1B231E}
.q-head .nm{font-size:14px}
.q-head .rs{font-size:12.5px; color:var(--ink-dim); margin-top:2px}
.q-head .chev{margin-left:auto; color:var(--ink-faint); transition:transform .2s}
.q-item.open .chev{transform:rotate(90deg)}
.q-body{display:none; padding:0 18px 18px; border-top:1px solid var(--line)}
.q-item.open .q-body{display:block}
.q-body pre{
  white-space:pre-wrap; word-wrap:break-word; font-family:'IBM Plex Mono',monospace;
  font-size:12.5px; line-height:1.7; color:var(--ink-dim); margin-top:15px;
}

/* Findings */
.find{display:flex; gap:11px; padding:11px 0; border-bottom:1px solid var(--line); font-size:13.5px}
.find:last-child{border-bottom:0}
.find .sev{
  font-size:9px; letter-spacing:0.09em; text-transform:uppercase; padding:2px 6px;
  border-radius:3px; height:fit-content; flex:0 0 auto; margin-top:2px;
}
.sev-high{background:rgba(180,84,74,0.15); color:var(--stop)}
.sev-medium{background:rgba(212,162,76,0.14); color:var(--warn)}
.sev-low{background:var(--line); color:var(--ink-dim)}

/* Empty states */
.empty{
  border:1px dashed var(--line); border-radius:9px; padding:34px 26px; text-align:center;
}
.empty h3{font-family:'Space Grotesk',sans-serif; font-size:16px; font-weight:500; margin-bottom:7px}
.empty p{color:var(--ink-dim); font-size:13.5px; max-width:430px; margin:0 auto}
.empty pre{
  text-align:left; background:var(--sunk); border:1px solid var(--line); border-radius:7px;
  padding:14px; margin-top:16px; font-family:'IBM Plex Mono',monospace; font-size:12px;
  color:var(--ink-dim); overflow-x:auto; white-space:pre;
}

/* Sparkline */
.spark{display:flex; align-items:flex-end; gap:2px; height:38px; margin-top:14px}
.spark i{flex:1; background:var(--live); border-radius:1px; opacity:.75; min-height:2px}
.spark i.bad{background:var(--stop); opacity:1}

.btn{
  display:inline-block; font-size:12.5px; padding:7px 13px; border-radius:6px;
  border:1px solid var(--line); color:var(--ink-dim); text-decoration:none; margin-top:14px;
}
.btn:hover{border-color:var(--live); color:var(--live)}

@media (max-width:860px){
  .shell{flex-direction:column}
  .rail{width:100%; flex:none; height:auto; position:static; padding:18px 0;
        display:flex; flex-direction:row; align-items:center; overflow-x:auto}
  .brand{border-bottom:0; border-right:1px solid var(--line); margin:0 14px 0 0;
         padding:0 18px 0 20px; flex:0 0 auto}
  .navlink{width:auto; white-space:nowrap; border-left:0; border-bottom:2px solid transparent; padding:8px 14px}
  .navlink.on{border-left:0; border-bottom-color:var(--live)}
  .rail-foot{display:none}
  .main{padding:22px 18px 50px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
:focus-visible{outline:2px solid var(--live); outline-offset:2px}
"""

JS = """
function show(v){
  document.querySelectorAll('.view').forEach(function(x){x.classList.toggle('on', x.id==='v-'+v)});
  document.querySelectorAll('.navlink').forEach(function(x){x.classList.toggle('on', x.dataset.v===v)});
  window.scrollTo(0,0);
}
function toggleQ(el){ el.closest('.q-item').classList.toggle('open'); }
"""


def state_colour(state):
    return {"success": "var(--live)", "failure": "var(--stop)", "timed_out": "var(--stop)",
            "in_progress": "var(--warn)", "queued": "var(--warn)", "never_run": "var(--idle)"}.get(state, "var(--idle)")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render(data):
    rev, health, hist = data["revenue"], data["health"], data["history"]
    seo, queue, comp = data["seo"], data["queue"], data["competitors"]
    runs, flags, attention = data["runs"], data["flags"], data["attention"]
    api_ok = data["api_ok"]
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

    # --- verdict ---
    if attention:
        top = attention[0]
        v_colour = "var(--stop)" if top["weight"] <= 1 else "var(--warn)"
        v_title = top["label"]
        rest = len(attention) - 1
        v_sub = top["detail"] + (f" - and {rest} other item{'s' if rest != 1 else ''} below" if rest > 0 else "")
    else:
        v_colour = "var(--live)"
        v_title = "Everything is running"
        v_sub = "No failures, no expiring certificates, nothing waiting on you."

    # --- pulse strip ---
    pulses = ""
    for i, s in enumerate(SYSTEMS):
        r = runs.get(s["key"], {"state": "never_run", "when": None, "url": None})
        col = state_colour(r["state"])
        bars = ""
        heights = [40, 70, 45, 90, 55, 75, 50]
        for j, h in enumerate(heights):
            lit = r["state"] == "success"
            bc = col if lit else ("var(--stop)" if r["state"] in ("failure", "timed_out") else "var(--idle)")
            op = "1" if lit or r["state"] in ("failure", "timed_out") else "0.45"
            bars += (f'<span class="bar" style="height:{h}%;background:{bc};opacity:{op};'
                     f'animation-delay:{i*0.05 + j*0.03:.2f}s"></span>')
        label = {"success": "ran " + humanise_age(r["when"]), "failure": "failed " + humanise_age(r["when"]),
                 "timed_out": "timed out", "never_run": "not set up yet"}.get(r["state"], r["state"])
        href = f'<a href="{r["url"]}" target="_blank" rel="noopener" aria-label="{esc(s["name"])} runs"></a>' if r.get("url") else ""
        pulses += (f'<div class="pulse"><span class="cad">{s["cadence"]}</span>'
                   f'<div class="bars">{bars}</div><div class="nm">{esc(s["name"])}</div>'
                   f'<div class="mt">{esc(label)}</div>{href}</div>')

    # --- attention rows ---
    if attention:
        att_rows = "".join(
            f'<button class="att-row" onclick="show(\'{a["view"]}\')">'
            f'<span class="pip" style="background:{"var(--stop)" if a["weight"]<=1 else "var(--warn)"};margin-top:6px"></span>'
            f'<span><span class="t">{esc(a["label"])}</span><br><span class="d">{esc(a["detail"])}</span></span>'
            f'<span class="go">&rsaquo;</span></button>' for a in attention)
        att_block = f'<div class="att">{att_rows}</div>'
    else:
        att_block = ('<div class="empty"><h3>Nothing needs you</h3>'
                     '<p>Every system ran, every site is healthy, and no reports are being held back.</p></div>')

    # --- figures ---
    up_display = f'{hist["uptime_pct"]}%' if hist["uptime_pct"] is not None else "-"
    figures = (
        f'<div class="figures">'
        f'<div class="fig"><div class="v">&pound;{rev["mrr"]}</div><div class="k">Monthly recurring</div></div>'
        f'<div class="fig"><div class="v">{rev["care_plan_clients"]}</div><div class="k">Care plan clients</div></div>'
        f'<div class="fig"><div class="v">{up_display}</div><div class="k">30-day uptime</div></div>'
        f'<div class="fig"><div class="v">{hist["checks"]}</div><div class="k">Checks run</div></div>'
        f'<div class="fig"><div class="v">{len(queue)}</div><div class="k">Awaiting you</div></div>'
        f'</div>')

    # --- client cards ---
    cards = ""
    for h in health:
        col = {"ok": "var(--live)", "needs_review": "var(--warn)", "urgent": "var(--stop)"}.get(h["status"], "var(--idle)")
        ssl = f'{h["ssl_days_left"]}d' if h["ssl_days_left"] is not None else "-"
        rt = f'{h["response_ms"]}ms' if h["response_ms"] is not None else "-"
        errs = ""
        if h["errors"]:
            errs = "".join(f'<div class="find"><span class="sev sev-medium">flag</span><span>{esc(e)}</span></div>'
                           for e in h["errors"])
            errs = f'<div style="margin-top:14px">{errs}</div>'
        cards += (f'<div class="card"><h3><span class="pip" style="background:{col}"></span>{esc(h["name"])}</h3>'
                  f'<a class="link" href="{esc(h["url"])}" target="_blank" rel="noopener">{esc(h["url"])}</a>'
                  f'<div class="metrics">'
                  f'<div class="metric"><div class="v">{rt}</div><div class="k">Response</div></div>'
                  f'<div class="metric"><div class="v">{ssl}</div><div class="k">Cert left</div></div>'
                  f'<div class="metric"><div class="v">{len(h["errors"])}</div><div class="k">Flags</div></div>'
                  f'</div>{errs}</div>')

    # --- sparkline ---
    spark = ""
    if hist["daily"]:
        for d in hist["daily"]:
            cls = " class=\"bad\"" if d["pct"] < 100 else ""
            spark += f'<i{cls} style="height:{max(6, d["pct"])}%" title="{d["date"]}: {d["pct"]}%"></i>'
        spark = (f'<div class="card"><h3>Uptime, last {len(hist["daily"])} day'
                 f'{"s" if len(hist["daily"]) != 1 else ""}</h3>'
                 f'<div class="spark">{spark}</div></div>')

    # --- queue view ---
    if queue:
        q_html = "".join(
            f'<div class="q-item"><button class="q-head" onclick="toggleQ(this)">'
            f'<span><span class="nm">{esc(i["kind"])} &middot; {esc(i["file"])}</span><br>'
            f'<span class="rs">{esc(i["reason"])}</span></span><span class="chev">&rsaquo;</span></button>'
            f'<div class="q-body"><pre>{esc(i["body"])}</pre></div></div>' for i in queue)
    else:
        q_html = ('<div class="empty"><h3>Queue is clear</h3>'
                  '<p>Reports land here when something unusual means they should not go out automatically. '
                  'Nothing is being held right now.</p></div>')

    # --- growth view ---
    if seo:
        g_html = ""
        for r in seo:
            fs = ""
            for sev in ("high", "medium", "low"):
                for f in r[sev]:
                    fs += (f'<div class="find"><span class="sev sev-{sev}">{sev}</span>'
                           f'<span>{esc(f["detail"])}</span></div>')
            if not fs:
                fs = '<div class="find"><span class="sev sev-low">clear</span><span>No issues found on this scan.</span></div>'
            g_html += (f'<div class="card" style="margin-bottom:14px"><h3>{esc(r["name"])}</h3>'
                       f'<div style="margin-top:6px">{fs}</div></div>')
    else:
        g_html = ('<div class="empty"><h3>No scan data yet</h3>'
                  '<p>Run the SEO Scan workflow once and findings will appear here, grouped by how much they matter.</p></div>')

    # --- competitor view ---
    if not comp["configured"]:
        c_html = ('<div class="empty"><h3>Competitor tracking is off</h3>'
                  '<p>Add rival sites to any client in clients.yaml and this fills in after two runs - the first '
                  'records a baseline, the second reports what changed.</p>'
                  '<pre>competitors:\n  - name: "Local Rival Ltd"\n    url: "https://theirsite.co.uk"</pre></div>')
    else:
        rows = ""
        for r in comp["records"]:
            if r["status"] == "unreachable":
                note = "could not be reached"
            elif r["is_first_run"]:
                note = "baseline recorded, changes show from next run"
            else:
                note = f'{len(r["added"])} added, {len(r["removed"])} removed'
            rows += (f'<div class="card" style="margin-bottom:12px"><h3>{esc(r["competitor_name"])}</h3>'
                     f'<a class="link" href="{esc(r["competitor_url"])}" target="_blank" rel="noopener">'
                     f'{esc(r["competitor_url"])}</a><div class="metrics"><div class="metric">'
                     f'<div class="v" style="font-size:14px">{esc(note)}</div>'
                     f'<div class="k">Watching for {esc(r["client_name"])}</div></div></div></div>')
        c_html = rows or '<div class="empty"><h3>No competitor data yet</h3><p>Run the Competitor Intel workflow.</p></div>'

    # --- systems view ---
    mode_note = ""
    if flags["test_mode"] or flags["force_send"]:
        mode_note = (f'<div class="card" style="border-color:var(--warn);margin-bottom:16px">'
                     f'<h3><span class="pip" style="background:var(--warn)"></span>Test mode is on</h3>'
                     f'<p style="color:var(--ink-dim);font-size:13.5px;margin-top:7px">'
                     f'Reports are going to {esc(flags["test_email"]) or "your test address"} instead of clients. '
                     f'Set test_mode and force_send_for_testing to false in clients.yaml when you are done.</p></div>')

    api_note = ""
    if not api_ok:
        api_note = ('<div class="card" style="border-color:var(--warn);margin-bottom:16px">'
                    '<h3><span class="pip" style="background:var(--warn)"></span>Run history unavailable</h3>'
                    '<p style="color:var(--ink-dim);font-size:13.5px;margin-top:7px">'
                    'The GitHub API could not be reached when this page was built, so system states below are unknown '
                    'rather than confirmed working.</p></div>')

    s_rows = ""
    for s in SYSTEMS:
        r = runs.get(s["key"], {"state": "never_run", "when": None, "url": None})
        col = state_colour(r["state"])
        label = {"success": "Ran cleanly", "failure": "Last run failed", "timed_out": "Last run timed out",
                 "never_run": "Not set up in this repo yet"}.get(r["state"], r["state"])
        btn = f'<a class="btn" href="{r["url"]}" target="_blank" rel="noopener">Open runs</a>' if r.get("url") else ""
        s_rows += (f'<div class="card" style="margin-bottom:12px">'
                   f'<h3><span class="pip" style="background:{col}"></span>{esc(s["name"])}'
                   f'<span class="tag" style="margin-left:auto">{s["cadence"]}</span></h3>'
                   f'<p style="color:var(--ink-dim);font-size:13.5px;margin-top:6px">{esc(s["job"])}</p>'
                   f'<p style="color:var(--ink-faint);font-size:12.5px;margin-top:4px">'
                   f'{esc(label)} &middot; {esc(humanise_age(r["when"]))}</p>{btn}</div>')

    queue_badge = f'<span class="count{" hot" if queue else ""}">{len(queue)}</span>'
    att_badge = f'<span class="count{" hot" if attention else ""}">{len(attention)}</span>'

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DM Ops</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head><body>
<div class="shell">
  <nav class="rail">
    <div class="brand"><div class="mark">DM Ops</div><div class="sub">Control</div></div>
    <button class="navlink on" data-v="deck" onclick="show('deck')">Deck {att_badge}</button>
    <button class="navlink" data-v="clients" onclick="show('clients')">Clients</button>
    <button class="navlink" data-v="queue" onclick="show('queue')">Needs you {queue_badge}</button>
    <button class="navlink" data-v="growth" onclick="show('growth')">Growth</button>
    <button class="navlink" data-v="competitors" onclick="show('competitors')">Competitors</button>
    <button class="navlink" data-v="systems" onclick="show('systems')">Systems</button>
    <div class="rail-foot">Built {stamp}<br>Rebuilds weekly</div>
  </nav>
  <main class="main">

    <section id="v-deck" class="view on">
      <div class="verdict">
        <span class="dot" style="background:{v_colour}"></span>
        <div><h1>{esc(v_title)}</h1><p>{esc(v_sub)}</p></div>
        <div class="stamp">{stamp}</div>
      </div>
      <div class="strip">{pulses}</div>
      {figures}
      <div class="eyebrow">What needs you</div>
      {att_block}
      <div class="eyebrow">Client sites</div>
      <div class="grid">{cards}{spark}</div>
    </section>

    <section id="v-clients" class="view">
      <div class="eyebrow">Client sites</div>
      <div class="grid">{cards}</div>
      <div class="eyebrow">Uptime history</div>
      {spark or '<div class="empty"><h3>No history yet</h3><p>Daily checks build this up over time.</p></div>'}
    </section>

    <section id="v-queue" class="view">
      <div class="eyebrow">Held for review</div>
      {q_html}
    </section>

    <section id="v-growth" class="view">
      <div class="eyebrow">Site improvement opportunities</div>
      {g_html}
    </section>

    <section id="v-competitors" class="view">
      <div class="eyebrow">Competitor watch</div>
      {c_html}
    </section>

    <section id="v-systems" class="view">
      <div class="eyebrow">Automation status</div>
      {mode_note}{api_note}{s_rows}
    </section>

  </main>
</div>
<script>{JS}</script>
</body></html>"""


def main():
    with open("clients.yaml") as f:
        config = yaml.safe_load(f)
    clients = config["clients"]
    business = config.get("business", {})

    runs = get_workflow_runs()
    flags = read_config_flags(business)
    health = compute_health(clients)
    seo = compute_seo(clients)
    queue = read_review_queue()
    competitors = compute_competitors(clients)

    data = {
        "revenue": compute_revenue(clients),
        "health": health,
        "history": compute_history(),
        "seo": seo,
        "queue": queue,
        "competitors": competitors,
        "runs": runs,
        "flags": flags,
        "api_ok": bool(runs),
        "attention": build_attention(health, seo, queue, flags, runs, competitors),
    }

    os.makedirs("dashboard", exist_ok=True)
    with open("dashboard/index.html", "w", encoding="utf-8") as f:
        f.write(render(data))

    slim = {k: v for k, v in data.items() if k != "queue"}
    slim["queue"] = [{"file": q["file"], "kind": q["kind"], "reason": q["reason"]} for q in queue]
    with open("dashboard/data.json", "w") as f:
        json.dump(slim, f, indent=2, default=str)

    print(f"Dashboard built. {len(data['attention'])} item(s) need attention.")


if __name__ == "__main__":
    main()
