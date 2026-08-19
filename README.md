# DM Ops

Automation for DM Web Services: client site monitoring, reporting, growth and social
content drafting, competitor intelligence, and a business dashboard, all running on
GitHub Actions.

- **Operating the system** (what runs, schedules, data flow, secrets, how to add a
  client, pause things, known limits, running cost): see
  [`docs/OPERATING-GUIDE.md`](docs/OPERATING-GUIDE.md).
- **Business context, brand standards, and technical conventions**: see
  [`KNOWLEDGE.md`](KNOWLEDGE.md).

## Running tests

Unit tests live in `tests/` and use Python's built-in `unittest` (no extra
dependencies). They cover the pure, offline-safe logic in `scripts/*.py` -
config parsing/schema, HTML-parsing helpers, and report/dashboard
data-transformation functions - and never send email, make network calls, or
touch the `test_mode` / `force_send_for_testing` flags.

Run the whole suite from the repo root:

```
python3 -m unittest discover -s tests -v
```

Run a single file:

```
python3 -m unittest tests.test_generate_report -v
```
