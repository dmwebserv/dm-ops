# Growth/SEO Agent - Phase 4 Test Plan

Run through these once both workflows are live, to confirm the system behaves correctly
before trusting it. Most of the detection logic itself was already verified offline against
known-answer HTML during the build (reversed attribute order, script-tag word count
inflation, empty alt attributes) - these tests are about the end-to-end system, not just
the regex.

## Test 1: Normal case - real clean site
Run `seo_check.py` then `generate_growth_report.py` against LWP or KCM as-is.
**Expect:** a findings list with whatever's genuinely present (likely OG tags, robots.txt,
sitemap - both sites probably don't have these), and a sensible top-3 list generated from it.

## Test 2: Site with no issues at all
Temporarily point a test client entry at a well-optimised site (e.g. a major companies's homepage) to
confirm the "skip if no findings" path works and doesn't error.
**Expect:** console output `No SEO findings for [client] - skipping` and no file written to
`reports/_review_queue/`.

## Test 3: Site unreachable
Temporarily set a client's `url` to a broken domain, run `seo_check.py`.
**Expect:** a single "high" severity finding about availability, no crash, other checks
correctly skipped (since there's no HTML to check).

## Test 4: Missing information (thin data)
Run `generate_growth_report.py` before `seo_check.py` has ever run (no `logs/seo/latest.json`).
**Expect:** this should fail clearly with a `FileNotFoundError`, not silently produce a
blank report. If it fails silently instead, that's a bug to fix - the script should error
loudly here, not send/produce empty content.

## Test 5: Duplicate/unusual HTML
Test 1 already covers this in principle (multiple H1s, reversed attributes) - re-confirm
against whichever real client site has the most non-standard HTML structure.

## Test 6: Tool/API failure
Temporarily use an invalid `ANTHROPIC_API_KEY` value, run `generate_growth_report.py`.
**Expect:** the script should fail with a clear API error in the Action log, not produce a
garbled or partial report file.

## Test 7: Unexpected AI output
Read the actual generated top-3 list critically once produced. Check specifically:
- Did it invent any finding not present in the raw data? (compare against `logs/seo/latest.json`)
- Did it use any em dashes or en dashes? (should be none - standard hyphens only)
- Is it actually prioritised (most impactful first), or just listing findings in scan order?
- Does it stay under ~220 words as instructed?

## Test 8: Human approval point
Confirm every report - regardless of content - lands in `reports/_review_queue/` and is
never auto-sent. This is intentional for v1 (see Phase 1 notes in KNOWLEDGE.md) - confirm
it's actually happening, not just assumed.

## After testing

If everything above checks out, the system is ready to document properly (README section,
same pattern as the Maintenance Agent) and mark complete on the roadmap. Consider then
whether findings-are-always-held-for-review should stay permanent (since these reports
double as sales material and may always warrant a human glance) or whether a similar
auto-send/hold-for-anomaly split makes sense once you trust the output quality.
