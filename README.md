# Website Maintenance Agent

Automated monitoring, triage, and reporting system for DM Web Services Care Plan clients.

## What it does

1. **Daily checks** (`check_sites.py`) - every day at 8am UTC, checks each client site for:
   - Uptime / server errors
   - SSL certificate expiry
   - Broken links (same-domain, first 30 found)
   - Presence of a contact form
   - Response time

2. **Notifications** (`notify.py`) - if any check comes back flagged, opens a GitHub Issue
   (🔴 urgent / 🟡 needs review) automatically. Silence = everything's fine, no issue created.

3. **Monthly reports** (`generate_report.py`) - on the 1st of each month, pulls the last 30
   days of history for each Care Plan client, calculates real numbers (uptime %, avg speed,
   SSL days left, issues found), and asks Claude to draft a plain-English update. Sends
   automatically via email (Resend) for clean months, or holds in a review queue for anything
   unusual.

## How it decides what to auto-send vs hold for review

A report is held in `reports/_review_queue/` instead of being sent automatically if:
- Fewer than 7 days of data exist for that period
- Uptime dropped below 99%
- SSL certificate has fewer than 14 days left
- 3 or more issues were flagged in the period

Otherwise, it sends automatically - no manual step required.

## Where data lives

Everything is in the `dm-ops` GitHub repo:

| Path | Contents |
|---|---|
| `clients.yaml` | Client register, business/sender config, test mode switches |
| `logs/latest.json` | Most recent check result per client |
| `logs/history/YYYY-MM-DD.json` | Daily snapshot, kept indefinitely |
| `reports/{client_id}/YYYY-MM.md` | Every generated report, sent or held |
| `reports/_review_queue/` | Reports currently awaiting your review |

## Tools connected

- **GitHub Actions** - runs the scheduled checks and report generation (free tier)
- **Anthropic API** - drafts report text (`ANTHROPIC_API_KEY` secret)
- **Resend** - sends the emails (`RESEND_API_KEY` secret), sending domain
  `updates.dmwebservices.co.uk`, verified via IONOS DNS (SPF/DKIM/DMARC)

## How to add a new client

Edit `clients.yaml`, add a new entry under `clients:`:

```yaml
  - id: newclient
    name: New Client Ltd
    url: https://newclient.co.uk
    care_plan: true
    contact_name: "Their Name"
    contact_email: "their@email.com"
    notes: ""
```

Set `care_plan: false` for one-off (non-Care Plan) clients if you want them monitored
but never sent automated reports.

## How to test safely (without emailing real clients)

In `clients.yaml`, under `business:`, set:

```yaml
  test_mode: true
  test_email: danny@dmwebservices.co.uk
  force_send_for_testing: true
```

- `test_mode: true` redirects every send to `test_email` instead of real clients, and
  prefixes the subject with `[TEST MODE]`.
- `force_send_for_testing: true` bypasses the hold-for-review checks, so you can see the
  actual email output even with thin data.

**Always set both back to `false` after testing** or reports will silently stop reaching
real clients.

## How to pause or disable

- To pause everything: go to **Actions** tab -> select the workflow -> **"..." -> Disable workflow**.
- To pause one client only: set `care_plan: false` in `clients.yaml` (still monitored, no reports/emails).
- To stop monitoring a client entirely: remove their entry from `clients.yaml`.

## Troubleshooting common problems

| Symptom | Likely cause |
|---|---|
| Workflow fails with exit code 128 on git push | Repo permissions reverted to read-only - check Settings -> Actions -> General -> Workflow permissions |
| `IndentationError` in Python | A code edit broke indentation - Python is whitespace-sensitive, check spacing carefully |
| Resend returns 401 | API key invalid, revoked, or has a typo - regenerate in Resend dashboard, re-add as `RESEND_API_KEY` secret |
| Resend returns a domain/sender error | `from_email` in `clients.yaml` doesn't match the verified domain in Resend exactly |
| Report shows placeholder-sounding output ("Hi there" etc.) | `contact_name` is blank for that client in `clients.yaml` |
| Uptime shows unexpectedly low with no real outage | Check `errors` array for that day - only "unreachable" or "Server error" count toward downtime; other flags (broken links, SSL warnings) don't |

## Expected monthly cost

- GitHub Actions: free (well within free tier minutes for this workload)
- Anthropic API: a few pence per report generated
- Resend: free (well under the 3,000 email/month free tier)
- **Total: effectively £0-5/month** at current client volume

## Security notes

- This system only ever **reads** client sites (GET/HEAD requests) - it has no write access
  to any client's live code or hosting.
- API keys are stored as GitHub encrypted secrets, never in code.
- Client contact details live in `clients.yaml` in a private repo only you can access.
- No client financial or sensitive personal data is stored or processed.
