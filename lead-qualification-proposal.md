# Lead Qualification System - Proposal (Phase 1/2, not yet approved or built)

## Why this next, over other remaining options

Of what's left on the original roadmap (Lead Qualification, BI Dashboard, Social Content,
Competitor Intelligence, Client Project Manager, Website Production System, Knowledge System
extensions), this ranks highest on revenue potential specifically - it directly affects
whether website enquiries turn into paying clients, which compounds every other system's
value. A BI Dashboard is more useful once there's more business data to show; this creates
new business.

## Phase 1 - Define

**What it does:** when someone submits an enquiry through a client's contact form (or your
own dmwebservices.co.uk form), automatically extract what they're asking for, flag if
information is missing, do a first-pass suitability check, and draft a qualified lead
record - so you open your inbox to a structured summary instead of a raw form dump.

**Who benefits:** you, directly - less time spent parsing vague enquiries, faster response
time to good leads, less time wasted on poor-fit enquiries.

**Problem it solves:** right now (per your safety rules and the original brief) this must
never auto-send quotes, promise deadlines, or make commitments - so the value is entirely in
triage and prep, not replacing you.

**What it automates:** extraction, categorisation, missing-info detection, a suggested
follow-up question draft (for you to send, not auto-sent).

**What still requires you:** every actual reply to a prospective client, any quote or
pricing, any deadline commitment.

## Phase 2 - Design (high level, pending the open questions below)

```
Enquiry submitted via contact form
  -> Form backend receives it (mechanism TBD - see open questions)
  -> Webhook/notification triggers a GitHub Action (or similar)
  -> Claude extracts: business type, service needed, location, budget signals,
     timeline, missing info
  -> Suitability check against your ideal client profile (trades/small business,
     matches your package range)
  -> Structured lead record written (GitHub Issue, reusing the existing pattern)
  -> You get notified with a ready-to-review summary, not a raw form dump
```

**Storage:** GitHub Issues again, for consistency with the rest of the system - no new
tool needed.

## Open questions - need your input before this can be built

This is the one place I can't make the call for you, because it depends on infrastructure
I don't have visibility into:

1. **How do your own site's and your clients' contact forms currently work?** Static
   HTML/JS sites need *something* to handle form submission - a third-party form service
   (e.g. Formspree, Netlify Forms, Web3Forms), a serverless function, or a plain `mailto:`
   link. Whatever it is determines whether this system is a simple webhook integration or
   needs form infrastructure built first.
2. **Is this for your own enquiries (dmwebservices.co.uk), client enquiries (e.g. LWP/KCM's
   contact forms), or both?** Changes the scope significantly - client enquiries would need
   their form data flowing back to you or to them, which needs clarifying per client.
3. **What does "good fit" mean for triage?** E.g. minimum budget signals, service type,
   location range - so the suitability check reflects real judgement, not a guess.

## Status

Not started. Waiting on the above before Phase 3 (build) begins, per your own rule not to
build without approval - this one has real unknowns I can't resolve on your behalf.
