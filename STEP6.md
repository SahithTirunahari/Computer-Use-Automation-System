> Historical milestone notes. See [README.md](README.md) and [REPORT.md](REPORT.md) for current behavior and verification status.

# Step 6: Same-session human handoff

## Run the interactive demo

Keep the portal running; Ollama is not needed. In a regular terminal with the
project virtual environment active:

```bash
python -m replay --member-id 12345 --headed --slow-mo 500 --demo-handoff --timeout 300
```

1. The existing search page opens in the replay browser.
2. The terminal says HUMAN CONTROL. Automation is paused before the lookup.
3. In THAT browser window, enter 12345 and click Search yourself.
4. Return to the same terminal and type `resume`, then press Enter.
5. The runner verifies the member result, takes control back, extracts fresh values,
   and returns GOAL_VERIFIED with $4,231.12.

To test rejection, search for 54321 while the command requested 12345, then type
`resume`. Control stays with you. Use Back to Search, search for 12345, and resume
again. Type `abort` to stop; EOF also aborts. For the business-outcome demo, run
with `--member-id 99999`, search for 99999 manually, and resume.

`--demo-handoff` is explicitly a simulated blocked checkpoint. It does not pretend
an application failure occurred and is recorded as DEMO_MANUAL_LOOKUP_REQUIRED.
The takeover, human actions, verification, and control transfer are real.

## Automatic escalation during normal replay

```bash
python -m replay --member-id 12345 --headed --human-handoff --timeout 300
```

On recoverable lookup errors (missing controls, browser operation timeout, an
unexpected result page, validation state, wrong identity, or stale/invalid outputs),
replay raises an intervention request and pauses. You manually reach the requested
member result, then resume. A maximum of two interventions is permitted.

Policy violations, blocked requests, unexpected popups/downloads, HTTP/script errors,
and ambiguous outcomes remain hard failures. Human mode does not override policy.
The request allowlist stays installed throughout manual control.

## Control model

`replay/handoff.py` owns an explicit state: automation -> human -> automation, or
human -> stopped. The same Playwright Page and BrowserContext stay alive throughout;
no replacement browser, login, or session is created. While the human owns control,
the runner issues no flow actions. It only records events and checks state when
resume is requested. Resume is rejected unless the requested identity and result
page pass the outcome checkpoint.

After resume, replay starts at the read-only outcome checkpoint and discards all
previous outputs. It does not blindly repeat a possibly completed submission.
The implementation is intentionally specific to this read-only lookup capability.
It is not a general mechanism to resume arbitrary transactions.

Terminal input uses cancellable POSIX event-loop stdin readiness, suitable for the
Mac terminal used here. There is no blocking input thread left behind on timeout.
Manual control defaults to a 180-second timeout; --handoff-timeout changes it.
The overall --timeout budget INCLUDES manual time and remains the final bound;
use --timeout 300 for the demo. Headed mode is required.

A cooperative single operator is assumed. This is explicit automation ownership,
not a desktop lock that prevents a person from clicking while automation owns control.
Browser closure or terminal disconnection may end the run. Desktop/native-app
handoff and multi-operator coordination are not implemented.

## Evidence and privacy

Existing replay evidence includes intervention_requested (capability, step, safe
reason, sanitized current-page structure), control_transferred, human_action,
human_navigation, and resume_rejected events. Manual event instrumentation survives
normal page navigation and captures click/input/keydown categories with known
control labels. Character keys, typed values, arbitrary labels, and destinations
are omitted/redacted. Enter/Tab/Escape can be recorded by name.

Only events received while control is human are retained. Pending callbacks on the
current page are drained before resume. This is a minimal web interaction log,
not a lossless OS-level recording: browser-chrome actions and events lost during
abrupt document destruction cannot be fully reconstructed. Raw values are never
stored, so these events are evidence of intervention, not replayable human actions.

## Files and verification

- replay/handoff.py: ownership, intervention requests, manual event capture, terminal commands.
- replay/runner.py: optional handoff on recoverable blocks and checkpoint-based resume.
- tests/test_handoff.py: same-page identity, ownership, rejected resume, abort/EOF,
  timeout, intervention limit, runtime-error blocking, and event redaction.

```bash
python -m unittest discover -s tests -p test_handoff.py -v
python -m unittest discover -s tests -q
```

All 48 offline tests pass; two opt-in browser tests are skipped. The interactive
handoff still needs verification in your regular terminal because this development
sandbox blocks Chromium launch. Retain the successful interactive demo's replay
folder for the final assignment evidence. Ordinary replay remains available without
the handoff flags. The final report and curated submission package remain pending.
