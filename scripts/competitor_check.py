"""
Competitor intelligence - change detection.

Fetches each configured competitor page, reduces it to readable text, stores a
dated snapshot, and diffs it against the most recent previous snapshot for that
same competitor. The point is to answer "what did they change since last time",
not "what does their site say" - so the output is a diff, not a scrape.

Competitors belong to DM Web Services itself, not to any individual client -
other web design studios are who DM Web Services competes with; a client's
own trade rivals are a different thing entirely and aren't tracked here.
Config is business-level in clients.yaml:

    business:
      competitors:
        - name: Some Local Studio
          url: https://example.co.uk

If none are configured, this does nothing at all - no directories, no files,
no output beyond a note. That is the expected state until competitors are
actually known.

Marketing pages are full of boilerplate that churns without meaning (cookie
banners, copyright years, nav text), so lines are noise-filtered before diffing.
Reading a diff of every trivial change is worse than reading nothing.
"""

import html
import json
import os
import re
import yaml
import requests
from datetime import datetime, timezone

HISTORY_DIR = "logs/competitors/history"
LATEST_PATH = "logs/competitors/latest.json"

# A line has to be long enough to plausibly be a sentence or a real heading.
# Anything shorter is nav labels, button text, or stray fragments.
MIN_LINE_LENGTH = 25

# Boilerplate that appears on nearly every page and changes for reasons that
# have nothing to do with the competitor's actual offering.
NOISE_PREFIXES = ("cookie", "accept", "privacy", "copyright")

# Cap on how much of a diff is worth recording. A redesign can change every
# line on a page; past a few dozen lines the detail stops being readable and
# the useful signal is simply "this was a big change".
MAX_DIFF_LINES = 40

USER_AGENT = "Mozilla/5.0 (compatible; dm-ops competitor check)"


def slugify(value):
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "competitor"


def page_to_lines(page_html):
    """Reduce raw HTML to a list of readable text lines.

    Headings and other block-level elements become their own lines, so a
    heading being added or reworded shows up as a discrete diff entry rather
    than being buried inside a run-on paragraph.
    """
    text = re.sub(
        r"<(script|style|noscript)\b[^>]*>.*?</\1>",
        " ",
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(
        r"</?(h[1-6]|p|div|section|article|header|footer|li|tr|td|th|ul|ol|blockquote)\b[^>]*>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)

    lines = []
    for raw_line in text.split("\n"):
        # \s covers the non-breaking spaces these pages are full of.
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return lines


def is_noise(line):
    if len(line) < MIN_LINE_LENGTH:
        return True

    stripped = line.lstrip("© ")
    if len(stripped) < len(line):
        # Opened with a copyright symbol, so it is a footer line.
        return True

    lowered = stripped.lower()
    if lowered.startswith(NOISE_PREFIXES):
        return True

    # A line that opens with a bare number is almost always a year, a price
    # fragment, a phone number, or a list index rather than a real statement.
    first_token = lowered.split(" ", 1)[0].strip(".,:;-()[]")
    if first_token.isdigit():
        return True

    return False


def readable_lines(page_html):
    """Noise-filtered, order-preserving, de-duplicated lines for one page."""
    seen = set()
    kept = []
    for line in page_to_lines(page_html):
        if is_noise(line) or line in seen:
            continue
        seen.add(line)
        kept.append(line)
    return kept


def fetch_lines(url):
    """Returns (lines, error). Exactly one of the two is meaningful."""
    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
    except requests.exceptions.RequestException as exc:
        return None, f"request failed: {exc.__class__.__name__}"

    if response.status_code >= 400:
        return None, f"HTTP {response.status_code}"

    lines = readable_lines(response.text)
    if not lines:
        return None, "no readable content extracted"
    return lines, None


def previous_snapshot(snapshot_name, today_str):
    """Most recent snapshot for this competitor from a date before today.

    Returns (lines, date_str) or (None, None) if this competitor has never
    been snapshotted, in which case today's run is a baseline.
    """
    if not os.path.isdir(HISTORY_DIR):
        return None, None

    for date_str in sorted(os.listdir(HISTORY_DIR), reverse=True):
        if date_str >= today_str:
            continue
        path = os.path.join(HISTORY_DIR, date_str, snapshot_name)
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            lines = [line.rstrip("\n") for line in f if line.strip()]
        if lines:
            return lines, date_str

    return None, None


def diff_lines(old_lines, new_lines):
    """Set difference, order-preserved against the list each line came from.

    Line-level set difference rather than a sequential diff: a page whose
    sections get reordered has not actually changed, and a sequential diff
    would report the whole page as churn.
    """
    old_set = set(old_lines)
    new_set = set(new_lines)
    added = [line for line in new_lines if line not in old_set]
    removed = [line for line in old_lines if line not in new_set]
    return added, removed


def check_competitor(competitor, today_str):
    name = competitor.get("name")
    url = competitor.get("url")
    if not name or not url:
        return {
            "name": name or "(unnamed)",
            "url": url or "",
            "status": "error",
            "error": "competitor entry needs both a name and a url",
        }

    result = {"name": name, "url": url}
    lines, error = fetch_lines(url)
    if error:
        # No snapshot is written on failure, so the last good snapshot stays
        # as the comparison base and a temporary outage does not read as
        # "they deleted their whole site" on the next run.
        result.update({"status": "error", "error": error})
        return result

    snapshot_name = f"{slugify(name)}.txt"
    day_dir = os.path.join(HISTORY_DIR, today_str)
    os.makedirs(day_dir, exist_ok=True)
    with open(os.path.join(day_dir, snapshot_name), "w") as f:
        f.write("\n".join(lines) + "\n")

    old_lines, compared_to = previous_snapshot(snapshot_name, today_str)
    if old_lines is None:
        result.update({
            "status": "baseline",
            "compared_to": None,
            "lines_captured": len(lines),
        })
        return result

    added, removed = diff_lines(old_lines, lines)
    result.update({
        "status": "changed" if (added or removed) else "unchanged",
        "compared_to": compared_to,
        "lines_captured": len(lines),
        "added_count": len(added),
        "removed_count": len(removed),
        "added": added[:MAX_DIFF_LINES],
        "removed": removed[:MAX_DIFF_LINES],
        "truncated": len(added) > MAX_DIFF_LINES or len(removed) > MAX_DIFF_LINES,
    })
    return result


def main():
    with open("clients.yaml") as f:
        business = yaml.safe_load(f).get("business", {})

    competitors = business.get("competitors") or []

    if not competitors:
        print("No competitors configured in clients.yaml - nothing to check.")
        return

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    results = [check_competitor(comp, today_str) for comp in competitors]
    for r in results:
        detail = r.get("error") or f"{r.get('added_count', 0)} added, {r.get('removed_count', 0)} removed"
        print(f"{r['name']}: {r['status']} ({detail})")

    os.makedirs(os.path.dirname(LATEST_PATH), exist_ok=True)
    with open(LATEST_PATH, "w") as f:
        json.dump({
            "checked_at": now.isoformat(),
            "date": today_str,
            "competitors": results,
        }, f, indent=2)

    print(f"Wrote {LATEST_PATH}")


if __name__ == "__main__":
    main()
