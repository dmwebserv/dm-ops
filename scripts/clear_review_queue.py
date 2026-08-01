"""
Clear old items from reports/_review_queue/.

The queue has no expiry today - items pile up forever once read, and the
dashboard's "awaiting you" count only ever grows. This is a deliberately
manual, unscheduled cleanup (see KNOWLEDGE.md / CLAUDE.md): silently
deleting things a human hasn't read yet would defeat the point of the
queue, so this is never wired into a scheduled workflow.

Only reports/_review_queue/ is touched. reports/{client_id}/ is the
permanent archive and this script never looks at it.
"""

import argparse
import os
import re
from datetime import date

REVIEW_QUEUE_DIR = "reports/_review_queue"
DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})")


def file_age_days(filename, today):
    match = DATE_PATTERN.search(filename)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    try:
        stamped = date(year, month, 1)
    except ValueError:
        return None
    return (today - stamped).days


def main():
    parser = argparse.ArgumentParser(description="Delete old files from reports/_review_queue/.")
    parser.add_argument("--older-than", type=int, default=60,
                         help="Delete files whose YYYY-MM date stamp is older than this many days (default 60).")
    parser.add_argument("--dry-run", action="store_true", help="List what would be deleted without deleting.")
    args = parser.parse_args()

    if not os.path.isdir(REVIEW_QUEUE_DIR):
        print(f"{REVIEW_QUEUE_DIR} does not exist - nothing to do.")
        return

    today = date.today()
    deleted, kept = [], []

    for filename in sorted(os.listdir(REVIEW_QUEUE_DIR)):
        if not filename.endswith(".md"):
            continue
        path = os.path.join(REVIEW_QUEUE_DIR, filename)
        age = file_age_days(filename, today)
        if age is None:
            kept.append(f"{filename} (no YYYY-MM date stamp found - kept)")
            continue
        if age > args.older_than:
            if not args.dry_run:
                os.remove(path)
            deleted.append(f"{filename} ({age} days old)")
        else:
            kept.append(f"{filename} ({age} days old)")

    verb = "Would delete" if args.dry_run else "Deleted"
    print(f"{verb} {len(deleted)} file(s):")
    for f in deleted:
        print(f"  - {f}")
    print(f"Kept {len(kept)} file(s):")
    for f in kept:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
