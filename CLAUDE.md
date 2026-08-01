# Project rules

Read KNOWLEDGE.md before making any change. It contains the business context,
brand standards, and technical conventions for this repo.

Non-negotiable:
- Never use em dashes or en dashes. Standard hyphens only.
- Business-wide config goes under `business:` in clients.yaml, client data under `clients:`.
- Never hardcode config in scripts.
- Testing is done via test_mode / force_send_for_testing flags in YAML, never by editing code.
- Never change test_mode to false without explicit instruction. That switch sends mail to real clients.
- Systems default to autonomous. Human review only for genuinely anomalous cases.
- Syntax-check every Python file you touch before committing.
