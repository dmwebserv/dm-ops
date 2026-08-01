"""Temporary smoke test: proves qc_review() still catches genuine issues
(em dash, invented figure) for content_type="internal_briefing" and
"social_caption", and confirms neither flags a missing greeting/sign-off.
Deleted after the live verification run - not part of the system.
"""
from qc_review import qc_review

BAD_DRAFT = (
    "This is a test draft with a real em dash — right here, and it "
    "claims 47 competitors were checked this month, which is not a real "
    "figure from the source facts provided."
)

for content_type in ("internal_briefing", "social_caption"):
    result = qc_review(
        draft_text=BAD_DRAFT,
        source_facts={"note": "no figures or counts are provided here"},
        contact_name="Kieran",
        sender_name="Danny",
        content_type=content_type,
    )
    print(f"=== {content_type} ===")
    print(result)
    print()
