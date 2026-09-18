# Computer-Use Automation System

A local, read-only Member Service Portal demonstrates model-driven discovery,
compilation into a typed capability, deterministic replay, and human takeover
in the same browser session. Discovery defaults to Ollama `qwen3-vl:4b-instruct`.
Replay makes no model calls.

See [REPORT.md](REPORT.md) for design and limits, [DEMO.md](DEMO.md) for the
presentation, and [evidence/submission](evidence/submission) for reviewed evidence.

## Setup

Run commands from the project directory. Python 3.11+ is required; the fresh
installation was verified with Python 3.13.3 on macOS. Terminal handoff uses
POSIX input handling; Windows handoff is not verified.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-agent.txt -c constraints-tested.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/playwright-browsers" python -m playwright install chromium
```

The full installation includes the optional OpenAI client, but no API key is
needed for Ollama or replay. Install Ollama separately, then:

```bash
ollama pull qwen3-vl:4b-instruct
ollama list
```

Keep the Ollama application running for discovery. If using its command-line
server instead, run `ollama serve` in a separate terminal; do not start a second
server if the application already serves it.

## Start the portal

In terminal 1, with the virtual environment active:

```bash
uvicorn app.main:app --reload
```

Keep that terminal running. Open http://localhost:8000. In terminal 2, change
into this project and activate the same environment for the remaining commands.

All data is fictional:

| Member ID | Name | Savings balance | Status |
| --- | --- | --- | --- |
| 12345 | Alice Johnson | $4,231.12 | Active |
| 54321 | Bob Smith | $850.50 | Active |
| 77777 | Carol Williams | $12,450.00 | Restricted |

`99999` produces the normal `MEMBER_NOT_FOUND` business outcome. Malformed
inputs are rejected. The portal has no database or authentication.

## Discover, compile, replay

Create a fresh evidence directory, then run two real model-driven discoveries:

```bash
demo_dir=$(mktemp -d evidence/demo.XXXXXX)
python -m agent --goal "Find the current savings balance for member 12345." --headed --slow-mo 500 --evidence-dir "$demo_dir/success"
python -m agent --goal "Find the current savings balance for member 99999." --headed --slow-mo 500 --evidence-dir "$demo_dir/not-found"
python -m capabilities.compiler \
  --success-run "$demo_dir"/success/discovery-*/steps.jsonl \
  --not-found-run "$demo_dir"/not-found/discovery-*/steps.jsonl \
  --output "$demo_dir/get_savings_balance.json"
python -m replay --artifact "$demo_dir/get_savings_balance.json" --member-id 54321 --headed --slow-mo 1000
python -m replay --artifact "$demo_dir/get_savings_balance.json" --member-id 99999 --headed --slow-mo 1000
```

Stop if a discovery fails. The deliberately narrow compiler accepts a clean
supported trace pair with matching submission actions; extra exploration or
different submission methods may require another pair. It does not invent
missing evidence or repair arbitrary traces. Use a fresh directory on retry.

To rebuild the shipped artifact from the recorded discovery evidence without
running a model:

```bash
rebuild_dir=$(mktemp -d evidence/rebuild.XXXXXX)
python -m capabilities.compiler \
  --success-run evidence/submission/discovery-805b4a7f969f/steps.jsonl \
  --not-found-run evidence/submission/discovery-cc2eb3e3ac67/steps.jsonl \
  --legacy-policy-binding \
  --output "$rebuild_dir/get_savings_balance.json"
diff capabilities/get_savings_balance.v1.json "$rebuild_dir/get_savings_balance.json"
```

The legacy flag explicitly migrates older redacted logs recorded before
parameter-reference events existed. It relies on the historical executor
policy restricting typed input to the requested member. New traces record the
binding directly.

## Replay without Ollama

You can quit Ollama for these commands. Keep the portal running.

```bash
python -m replay --member-id 12345 --headed --slow-mo 1000
python -m replay --member-id 54321 --headed --slow-mo 1000
python -m replay --member-id 99999 --headed --slow-mo 1000
python -m replay --member-id abc
```

Expected results: success with $4,231.12; success with $850.50;
`MEMBER_NOT_FOUND`; and `INVALID_INPUT`, respectively. Replay checks the member
identity and reads the current displayed balance; it does not cache an answer.

## Human takeover

```bash
python -m replay --member-id 12345 --headed --demo-handoff --timeout 300
```

The demo deliberately pauses automation. In the browser it opened, search for
12345 and reach Member Details. Type `resume` in the terminal. The runner
rechecks the page and requested identity before extracting results. Type
`abort` to stop instead. A wrong-member page must be corrected before resume.

`--demo-handoff` is an explicit simulated interruption. `--human-handoff`
enables escalation for supported recoverable runtime failures. Both retain the
same browser context and page. Policy violations remain hard stops. Manual
time counts toward the overall timeout; interventions are bounded.

## Verification

```bash
python -m unittest discover -s tests -q
python -m pip check
```

Fresh-environment result: 55 tests, 53 passed, 2 browser tests skipped; no broken
requirements. Browser tests must be enabled explicitly in a terminal that can
launch Chromium:

```bash
RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -p 'test_*browser*.py' -v
python verify_portal.py --headed --slow-mo 1000
```

The saved evidence includes actual local-model discovery, deterministic replay,
not-found, and successful human resume. Wrong-member resume and abort have
automated coverage; their interactive checks are listed in DEMO.md. Browser
launch was blocked in the assistant sandbox, so these were not freshly
browser-verified during submission preparation.

## Evidence and code

Runtime evidence is redacted JSONL under `evidence/`. Only the reviewed
`evidence/submission/` bundle is intended for version control. Typed values,
member values, model prose, and screenshots are not retained in these logs.
CLI results and portal access logs are outside this redaction boundary; use
fictional data for the demo. Source hashes identify the compiler inputs but do
not cryptographically attest how a run occurred.

- `app/`: local target application.
- `agent/`: observation, model proposals, policy, execution, verification.
- `capabilities/`: typed schema, compiler, canonical JSON capability.
- `replay/`: deterministic runner and same-session handoff.
- `tests/`: schema, compiler, policy, replay, handoff and browser checks.
- `constraints-tested.txt`: versions verified in a fresh environment.

STEP3.md through STEP6.md are historical implementation notes; this README and
REPORT.md describe the current submission. General query routing, desktop
execution, and multi-tenant deployment are not implemented.
