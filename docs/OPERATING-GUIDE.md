# DM Ops - Operating Guide

This is the guide for running the automation in this repo when you've lost all context -
six months from now, after a break, or handing it to someone else. It tells you what runs,
what it produces, what to do when something breaks, and what its real limits are.

For brand standards, business context, and technical conventions (how config is
structured, writing style rules, lessons learned from past bugs), see `KNOWLEDGE.md` -
this guide doesn't repeat that, it links to it.

## The seven systems

All of these are GitHub Actions workflows in `.github/workflows/`, runnable on their
schedule or manually via **Actions tab -> select workflow -> Run workflow**.

| Workflow file | Runs | What it does | What it produces |
|---|---|---|---|
| `site-checks.yml` | Daily, 8am UTC | Checks each client site: uptime, SSL expiry, broken links (same-domain, first 30), presence of a `<form>` tag, response time. Opens a GitHub Issue if anything is flagged (silence = all clear). | `logs/latest.json`, `logs/history/YYYY-MM-DD.json`, a GitHub Issue if flagged |
| `seo-checks.yml` | Weekly, Monday 8am UTC | Scans each client's homepage for on-page SEO signals: title tag, meta description, H1 structure, image alt text, Open Graph tags, viewport meta, robots.txt/sitemap.xml presence, word count. | `logs/seo/latest.json`, `logs/seo/history/YYYY-MM-DD.json` |
| `growth-report.yml` | Monthly, 1st at 9am UTC | Reads the latest SEO findings, asks Claude to pick the top 3 highest-impact actions per client in plain English. Always held for review (doubles as sales/upsell material). | `reports/{client_id}/growth-YYYY-MM.md`, `reports/_review_queue/{client_id}-growth-YYYY-MM.md` |
| `monthly-report.yml` | Monthly, 1st at 9am UTC | Reads the last 30 days of site-check history, calculates real numbers (uptime %, avg response time, SSL days left, issues), drafts a plain-English health update, runs it through QC, and either emails it (via Resend) or holds it for review if something's anomalous or QC has a real concern. | `reports/{client_id}/YYYY-MM.md`, sometimes `reports/_review_queue/{client_id}-YYYY-MM.md`, an outbound email |
| `social-drafts.yml` | Monthly, 1st at 9am UTC | Fetches each client's own homepage, drafts 3 social post captions grounded in real site content. Always held for review (needs a human pass + real photos before posting - never auto-posted anywhere). | `reports/{client_id}/social-YYYY-MM.md`, `reports/_review_queue/{client_id}-social-YYYY-MM.md` |
| `competitor-intel.yml` | Monthly, 1st at 6am UTC (ahead of the 9am reports) | Competitors belong to DM Web Services, not to individual clients. If `business.competitors` is configured in `clients.yaml`, fetches each competitor URL, diffs against the last snapshot, and - only for genuine detected changes - drafts a single internal briefing about DM Web Services' own market. Does nothing at all if no competitors are configured. | `logs/competitors/history/YYYY-MM-DD/*.txt`, `logs/competitors/latest.json`, `reports/_business/competitors-YYYY-MM.md`, `reports/_review_queue/business-competitors-YYYY-MM.md` (only when something changed) |
| `dashboard.yml` | Weekly, Monday 7am UTC | Rebuilds a single-page console: revenue, client health, uptime history, SEO findings, competitor watch, review queue, and live pass/fail status of every workflow above (via the GitHub Actions API). | `dashboard/index.html`, `dashboard/data.json` |

There's an eighth workflow, `claude.yml`, which is not part of the business automation -
it's what runs when you `@claude` an issue or PR comment, i.e. how this whole system gets
built and fixed. It has no schedule; it fires on `issue_comment`, `pull_request_review_comment`,
and `issues: opened/assigned`.

## Data flow: what writes where

**Inputs** (you edit these):
- `clients.yaml` - the only file you should routinely hand-edit. Client register, and
  business config (sender name, test mode, care plan pricing, `business.competitors` -
  see "How to add a competitor" below).

**Working data** (machine-written, safe to delete and let regenerate - except history, which
is cheap to keep and expensive to lose):
- `logs/latest.json`, `logs/history/YYYY-MM-DD.json` - site-check results. History is the
  input to `monthly-report.yml`'s 30-day rollup; losing recent history thins that data and
  can trigger a "thin sample" hold.
- `logs/seo/latest.json`, `logs/seo/history/YYYY-MM-DD.json` - SEO scan results.
- `logs/competitors/history/YYYY-MM-DD/{competitor-slug}.txt`,
  `logs/competitors/latest.json` - competitor page snapshots and the latest diff (business-
  level - one snapshot set for DM Web Services' own market, not per client). The most
  recent dated folder *before today* is what tomorrow's run diffs against - don't delete the
  most recent history folder or the next run will treat it as a fresh baseline.

**Outputs** (the actual deliverables):
- `reports/{client_id}/YYYY-MM.md`, `reports/{client_id}/growth-YYYY-MM.md`,
  `reports/{client_id}/social-YYYY-MM.md` - every per-client report ever generated, sent or
  held. This is the permanent archive. Nothing in this repo ever deletes from here
  automatically.
- `reports/_business/competitors-YYYY-MM.md` - the same permanent archive, but for the
  business-level competitor briefing (there's no client to file it under).
- Outbound emails via Resend (monthly health reports only - nothing else sends anywhere).

**Review queue** (transient, the one place designed to be cleared):
- `reports/_review_queue/{client_id}[-growth|-social]-YYYY-MM.md`,
  `reports/_review_queue/business-competitors-YYYY-MM.md` - copies of held reports, for you
  to read. See "Clear the review queue" below.

**Dashboard** (a read-only view built from everything above):
- `dashboard/index.html`, `dashboard/data.json` - rebuilt weekly from `clients.yaml`, all
  the `logs/` data, the review queue, and live GitHub Actions run status. Never a source of
  truth itself - if it looks wrong, check the underlying files, not the dashboard.

## Secrets and external services

| Secret / service | Used by | What breaks if it fails |
|---|---|---|
| `ANTHROPIC_API_KEY` (GitHub secret) | `generate_report.py`, `generate_growth_report.py`, `generate_social_drafts.py`, `generate_competitor_report.py`, `qc_review.py` (used by all four) | Any of these scripts fails immediately and loudly (uncaught API error) - no partial or garbled report is ever written, because the "commit" step in each workflow only runs if the drafting step succeeded. Worst case: that month's report/briefing simply doesn't get generated until the key is fixed and the workflow re-run (manually, via workflow_dispatch - it won't retry itself). |
| `RESEND_API_KEY` (GitHub secret) | `generate_report.py` only, for the actual send | If this is bad, the email send raises and crashes `generate_report.py` - but this can happen *after* some clients in the loop were already drafted successfully in that run. Because the failure aborts the whole script, the commit step is skipped entirely, so **no client's report is committed that run**, not just the one that failed to send. Re-run once the key is fixed. |
| Resend sending domain / IONOS DNS (SPF, DKIM, DMARC on `updates.dmwebservices.co.uk`) | Email deliverability | This is the one silent failure mode: if DNS records lapse or get misconfigured, Resend's API call can still succeed (200 OK) while the email itself gets spam-filtered or bounced at the recipient's end. Nothing in this system currently detects that - check Resend's own dashboard/logs periodically, don't rely on the workflow going green. |
| `GITHUB_TOKEN` (auto-provided by Actions, no setup needed) | Every workflow's commit/push step; `notify.py` (creates issues); `generate_dashboard.py` (reads Actions API for run status) | If repo Settings -> Actions -> General -> Workflow permissions isn't "Read and write", every commit step fails with exit code 128 (this is the #1 historical failure mode - see `KNOWLEDGE.md`). If `notify.py`'s issue-creation call fails, `site-checks.yml`'s commit step is also skipped that day (same all-or-nothing step behavior as above), so that day's check results don't get committed either. |
| GitHub Actions itself | All scheduling and compute | If Actions is down or disabled for the repo, nothing runs, nothing notifies you that nothing ran - there's no external heartbeat check. The dashboard will show stale "last ran" times next time it *does* rebuild. |

## How to add a client

Edit `clients.yaml`, add an entry under `clients:`:

```yaml
  - id: newclient
    name: New Client Ltd
    url: https://newclient.co.uk
    care_plan: true
    contact_name: "Their Name"
    contact_email: "their@email.com"
    notes: ""
```

Set `care_plan: false` to keep a client monitored (site checks, SEO scans) without ever
generating or sending reports for them.

## How to add a competitor

Competitors belong to DM Web Services, not to any individual client - this tracks who DM
Web Services competes with (other web design studios), not a client's own trade rivals.
Add to `business.competitors` in `clients.yaml`:

```yaml
business:
  ...
  competitors:
    - name: "Some Local Studio"
      url: "https://example.co.uk"
```

The first `competitor-intel.yml` run after adding one records a baseline only (no briefing).
The next run compares against it and drafts a single briefing - covering every competitor
that changed, not one per competitor - only if something commercially meaningful actually
changed. See "Known limits" below for what it can and can't see.

## How to clear the review queue

`reports/_review_queue/` has no automatic expiry - it only grows. Run
`scripts/clear_review_queue.py` yourself when you want to clear old items you've already
read:

```
python3 scripts/clear_review_queue.py --dry-run              # see what would go, default 60 days
python3 scripts/clear_review_queue.py --older-than 30         # actually delete anything older than 30 days
```

This only ever touches `reports/_review_queue/` - it never touches `reports/{client_id}/`,
which is the permanent archive. It's deliberately not wired into any scheduled workflow;
run it yourself when you've actually read what's in there.

## How to pause or stop things

- **Pause one workflow**: Actions tab -> select the workflow -> "..." -> Disable workflow.
  It won't run on schedule or show up for manual triggering until re-enabled.
- **Pause reporting for one client without stopping monitoring**: set `care_plan: false` in
  `clients.yaml`. Site checks and SEO scans keep running; no reports, emails, or social
  drafts get generated for them.
- **Stop monitoring a client entirely**: remove their entry from `clients.yaml`.
- **Stop everything at once**: disable all seven scheduled workflows individually (there's
  no single kill switch - each is a separate Actions toggle). `claude.yml` is unaffected by
  this since it's not on a schedule; disable it separately if you also want to stop `@claude`
  responding to issues/PRs.
- **Stop reports reaching real clients without disabling anything**: set `test_mode: true`
  in `clients.yaml`. This redirects every send to `test_email` and still runs everything
  else normally - the safest way to pause output without pausing the system.

## Known limits

- **QC is a probabilistic second opinion, not a guarantee.** It meaningfully reduces the
  chance of a bad report reaching a client, but a QC pass is not proof a report is correct,
  and identical drafts can pass one run and fail the next. Full detail and a concrete
  example in `KNOWLEDGE.md`'s "QC layer notes" section.
- **Site monitoring records detection, not repair.** `site-checks.yml` tells you a link is
  broken or SSL is expiring; nothing in this system fixes anything. Reports are written to
  never imply otherwise (they say an issue "has been flagged", never that it's "resolved").
- **Competitor tracking only sees public page text, fetched without a browser.** It's a
  plain HTTP GET plus HTML stripping - no JavaScript execution, so content rendered
  client-side (many modern SPA-style sites) won't be seen at all. It also can't see
  anything behind a login, and diffs are a line-level set comparison, not a sequential
  diff - a page that gets reordered without any real content change won't be reported as
  changed (this is deliberate), but genuinely new content that happens to match old wording
  won't register either.
- **Workflow files (`.github/workflows/*.yml`) cannot be created or edited by the `@claude`
  bot** - GitHub blocks a GitHub App token from touching that path without an explicit
  `workflows` permission grant, as a deliberate security boundary. Changes to workflow files
  need a local Claude Code session (one with your own git credentials, not the issue-driven
  bot) or manual editing via the GitHub web UI. Full detail in `KNOWLEDGE.md`.

## Realistic monthly running cost

At the current scale (2 care-plan clients, competitor tracking off):

- **GitHub Actions**: free - all seven workflows combined run only a few minutes a month
  (daily site checks are the bulk of it, at roughly a minute each), well inside the free
  tier for a private repo.
- **Anthropic API**: roughly a dozen short Claude calls a month (report/growth/social
  drafting plus their QC passes) - a few pence to low single-figure pounds a month.
  The competitor briefing only adds calls once `business.competitors` is populated *and*
  something actually changed, so this stays near zero until you turn that on.
- **Resend**: free - miles under the 3,000 email/month free tier at this client count.
- **Total: realistically £0-5/month**, scaling roughly linearly with client count (a few
  more Claude calls and site checks per client added) - Actions and Resend both have enough
  free-tier headroom that neither is likely to become the binding cost even at 10-20x the
  current client count.
