> Historical milestone notes. See [README.md](README.md) and [REPORT.md](REPORT.md) for current behavior and verification status.

# Step 5: Deterministic replay

## What is implemented

`replay/runner.py` loads the versioned capability, validates its input, binds the
member ID, and executes the recorded steps. `replay/__main__.py` provides
`python -m replay`; `replay/__init__.py` defines the package. No model-provider
module is imported, no model API is called, and no API key is required. The
runtime dependencies are already installed; a new environment only needs
`requirements-dev.txt`, which includes the application and Playwright dependencies.

The same JSON file is used for every member. The runner handles:

- A five-digit string input; invalid input fails before browser launch.
- Exact semantic targets and the existing read-only request/action policy.
- Submission followed by the artifact's bounded Details/Not-Found checkpoint.
- Matching member identity, output formats, and rechecking outputs against live UI.
- Not-found as a business outcome with empty outputs, not an exception.
- Ambiguous outcomes, app validation alerts, wrong identities, stale outputs,
  HTTP errors, unexpected dialogs/popups/downloads, and blocked requests as failures.
- Up to one retry of initial navigation on timeout; no automatic resubmission.
- A 60-second overall deadline, with bounded browser cleanup afterward.

Known outcome polling is deterministic and bounded. It does not call a model to
interpret an unexpected page. Permission/session pages that have no explicit
handler stop as unexpected-state/timeouts; they are not guessed away.

## Run it

Keep the portal running. Ollama can be closed. In a normal terminal:

```bash
cd /path/to/computer-use-automation
source .venv/bin/activate
python -m replay --member-id 12345 --headed --slow-mo 1000
python -m replay --member-id 54321 --headed --slow-mo 1000
python -m replay --member-id 99999 --headed --slow-mo 1000
```

Expected results (not claimed live replay results):

| Input | Status | Code | Balance |
| --- | --- | --- | --- |
| 12345 | success | GOAL_VERIFIED | $4,231.12 |
| 54321 | success | GOAL_VERIFIED | $850.50 |
| 99999 | business_outcome | MEMBER_NOT_FOUND | No outputs |

The default artifact is `capabilities/get_savings_balance.v1.json`. To use the
rebuilt file explicitly:

```bash
python -m replay --artifact capabilities/get_savings_balance.rebuilt.json --member-id 54321 --headed --slow-mo 1000
```

Optional flags: `--url` (portal origin), `--policy`, `--timeout`, `--evidence-dir`.
Omit `--headed` for headless execution. Success and business outcomes exit 0;
failures exit 1; invalid command-line options exit 2.

Validate the invalid-input path:

```bash
python -m replay --member-id abc
```

Expected: `failure / INVALID_INPUT` at step 0, with no browser launch.

## Evidence

Each invocation creates `evidence/replay-<id>/steps.jsonl`. The header includes
`mode=deterministic_replay`, `model_calls=0`, capability version, and the SHA-256
of the exact artifact. Steps, checkpoint results, retry events, and final outcome
are logged. Typed and extracted values are redacted; free-form exception messages
and full URLs are not logged. Outputs are returned to the terminal only.

Failures after browser launch include a sanitized structural `failure-dom.json`.
Prelaunch failures record that a browser snapshot was unavailable; malformed
artifact/policy failures are recorded as structured results. Logs remain gitignored
until reviewed and deliberately included in the final evidence package.

`model_calls=0` describes this execution path, not a measured provider counter:
the replay dependency graph contains no model client. An isolated-process test
also verifies that OpenAI, Ollama adapters, and HTTPX are not imported.

## Tests and current verification

```bash
python -m unittest discover -s tests -p test_replay.py -v
python -m unittest discover -s tests -v
```

`tests/test_replay.py` tests input binding, all checkpoint paths, delayed state,
output checks, redaction, short-circuiting on not-found, total timeout/cleanup,
and the absence of model imports using controlled browser doubles.

Real browser replay test (portal must be running; no Ollama needed):

```bash
RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -p test_replay_browser.py -v
```

This reads the delivered artifact and runs all three IDs through the real runner.
Its evidence is temporary; use the CLI runs above to retain submission evidence.

The development environment verified offline tests and the invalid-input CLI path.
A live replay attempt returned BROWSER_LAUNCH_FAILED because Chromium cannot launch
in this sandbox. Successful live replays must still be verified in your regular
terminal. The earlier successful discovery runs are not replay verification.

## Remaining assignment work

Step 5 implementation is ready for live verification. The full take-home still
needs same-session human takeover/resume, final REPORT.md, and curated discovery
and replay evidence. Those are not implemented by this milestone.
