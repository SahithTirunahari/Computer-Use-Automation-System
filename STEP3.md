> Historical milestone notes. See [README.md](README.md) and [REPORT.md](REPORT.md) for current behavior and verification status.

# Step 3: LLM-driven browser discovery

## Status and scope

Implemented a real model adapter and browser loop for the goal:
`Find the current savings balance for member 12345.`

Offline tests exercise validation, policy, verification, loop bounds, and API request
construction. These are NOT genuine discovery runs. A live model demonstration has
not yet been completed: no OPENAI_API_KEY was available to the development session,
and its macOS sandbox blocked Chromium from launching (MachPort permission error).
Run the commands below from a regular terminal, where the regression script works.

The scope is one savings-balance lookup at a time. The goal must contain the words
`savings` and `balance` and one distinct five-digit ID. This narrow input contract
lets code independently check the requested identity. The model still decides the
browser actions; there is no predefined action sequence in the live agent.

## Run with local Ollama (default)

Ollama is now the default provider, using `qwen3-vl:4b-instruct`. No OpenAI key
is required. Keep the Ollama app open and the portal running. From this project:

```bash
source .venv/bin/activate
pip install -r requirements-agent.txt
python -m agent --goal "Find the current savings balance for member 12345." --headed --slow-mo 1000
```

Then repeat with member 54321 and 99999. Expected balances are $4,231.12 and
$850.50; 99999 should return MEMBER_NOT_FOUND. These are expected results, not
claimed live-run evidence.

The adapter in `agent/ollama.py` calls the local `/api/chat` endpoint with a
screenshot, accessibility/text observation, recent steps, and the action JSON
schema. Responses are validated through the same Pydantic models and executor.
It uses temperature 0, an 8,192-token context, and a 1,600-token output limit.
The overall default deadline is now 600 seconds; Ollama requests are capped at
120 seconds within that deadline. Initial model loading can take longer than
subsequent turns. `--model`, `--ollama-url`, and `--timeout` are configurable.
Only local HTTP Ollama endpoints are accepted.

If you see OLLAMA_UNAVAILABLE, open the Ollama app, or run `ollama serve` in a
separate terminal if it is not already running. For OLLAMA_MODEL_NOT_FOUND,
run `ollama pull qwen3-vl:4b-instruct`. OLLAMA_TIMEOUT means the local model
request exceeded its time budget. Check memory pressure and close heavy apps.

Ollama adapter tests are offline. The development environment could not connect
to port 11434, and Chromium launch remains sandbox-blocked; run the genuine
end-to-end check in your normal terminal. The existing OpenAI provider remains
optional and requires `--provider openai`.

## Optional OpenAI setup and run

Keep the portal running on http://localhost:8000 in its existing terminal.
In a second macOS terminal:

```bash
cd /path/to/computer-use-automation
source .venv/bin/activate
pip install -r requirements-agent.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/.venv/playwright-browsers" python -m playwright install chromium
```

Configure an API key in this terminal. For the default macOS zsh shell, the
following prompts without displaying the key or placing its value in shell history:

```zsh
read -s "OPENAI_API_KEY?OpenAI API key: "
export OPENAI_API_KEY
```

Do not paste the key into chat, code, or a tracked file. The program reads the
environment directly and does not load `.env` files.

Select a model supporting images and Structured Outputs. For example, the official
[GPT-4.1 documentation](https://developers.openai.com/api/docs/models/gpt-4.1)
lists both. Account access and API billing must be configured separately.

```bash
export OPENAI_MODEL=gpt-4.1
python -m agent --provider openai --goal "Find the current savings balance for member 12345." --headed --slow-mo 1000
```

Then test the other outcomes:

```bash
python -m agent --provider openai --goal "Find the current savings balance for member 54321." --headed --slow-mo 1000
python -m agent --provider openai --goal "Find the current savings balance for member 99999." --headed --slow-mo 1000
```

Expected results (examples, not recorded live evidence):

- 12345: `status=success`, `outputs.member_id=12345`, `outputs.savings_balance=$4,231.12`.
- 54321: `status=success`, `outputs.member_id=54321`, `outputs.savings_balance=$850.50`.
- 99999: `status=business_outcome`, `code=MEMBER_NOT_FOUND`, empty outputs.

Defaults: 10 decision attempts, 600-second overall deadline, 5-second browser
operations, model calls capped at 45 seconds with automatic SDK retries disabled.
Use `--max-steps`, `--timeout`, `--url`, `--model`, `--policy`, or `--evidence-dir`
to configure them. The overall deadline cancels pending async operations; bounded
cleanup can add a few seconds. Two consecutive recoverable failures or three
identical actions against the same observation stop the run. Success and known
business outcomes exit 0; failures exit 1; invalid CLI configuration exits 2.

## Files and boundaries

| File | Responsibility |
| --- | --- |
| agent/actions.py | Strict Pydantic action and result types |
| agent/observer.py | Live accessibility snapshot, visible text, in-memory screenshot |
| agent/decision.py | OpenAI Responses API adapter, no browser execution |
| agent/prompts.py | Goal-following and one-action instructions |
| agent/executor.py | Semantic target resolution, execution, independent result verification |
| agent/policy.py and policy.json | Configured request/action allowlist and read-only control restrictions |
| agent/evidence.py | Redacted JSONL and sanitized failure snapshot |
| agent/agent.py | CLI, browser lifecycle, deadlines, observe-decide-act loop |
| agent/__init__.py and __main__.py | Package and `python -m agent` entry point |
| requirements-agent.txt | Optional agent dependencies |
| tests/test_agent.py | Offline unit tests; no API key or browser needed |
| tests/test_browser_integration.py | Opt-in live-browser checks with explicitly scripted test decisions |

The app and `verify_portal.py` are unchanged. The observer/executor form the browser
adapter boundary. A future desktop implementation would need its own observation
and target resolution; definition-list targeting is specific to this portal, not
a claim of general legacy-app support.

## Main action schema

Each response contains one `next_action`, a union of separate strict models.
All actions carry a short `reason`. Extra fields, raw selectors, code execution,
and arbitrary browser commands are rejected.

| Action | Required fields beyond action/reason |
| --- | --- |
| click | role target |
| type | role target, value |
| keypress | role target, key (Enter/Tab/Escape) |
| scroll | direction (up/down), pixels (1–800) |
| extract | definition target, output_name (member_id/savings_balance) |
| wait | target, condition=visible |
| done | result: success with output_keys, business_outcome with code, or failure with code |

Example:

```json
{
  "next_action": {
    "action": "extract",
    "target": {"kind": "definition", "label": "Current Savings Balance"},
    "output_name": "savings_balance",
    "reason": "Read the balance associated with the visible savings label"
  }
}
```

Success references stored data:

```json
{
  "next_action": {
    "action": "done",
    "result": {"status": "success", "output_keys": ["member_id", "savings_balance"]},
    "reason": "Both required outputs have been extracted"
  }
}
```

## Observation, decisions, and verification

The observer reads the live body accessibility snapshot, visible text, URL, and
viewport screenshot. Nothing imports `app.data` or calls a member-data API.
The fake UI content is sent to the selected model, with the goal, last six steps,
and extracted values. Screenshots remain in memory; they are not written to disk.

The adapter uses the official [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
Pydantic integration and [image input](https://developers.openai.com/api/docs/guides/images-vision)
format. Every returned action is validated again before policy checks and execution.
Refusals, incomplete outputs, and invalid actions cannot become executable commands.

Conceptual loop (the actual implementation is in agent/agent.py):

```python
for step in range(max_steps):
    observation = await observe(page)
    decision = await decider.decide(goal, observation, history, outputs, remaining_time)
    action = validate(decision)
    policy.check_action(action, requested_member_id)
    if action.action == "done":
        return await verify_done(page, action, outputs, requested_member_id, step)
    await execute_action(page, action, outputs)
    record_redacted_step()
```

Targets must match exactly one visible control. Known labels resolve through
roles/names or a rendered definition term and its associated value. The latter
uses adapter-owned DOM logic; the model cannot supply CSS or XPath.

Success requires explicit extraction of both member ID and balance. Code checks
that the member matches the goal and both stored values still match the live
Member Details page. Interactions clear old extractions. Not-found requires a
visible heading, a matching member-specific message, and the matching URL parameter.
A model assertion alone never establishes success or Member Not Found.

## Policy and evidence

`agent/policy.json` specifies allowed origins, paths, and actions. Requests are
intercepted before dispatch and must use GET on an allowed URL. The executor only
permits known lookup controls; typing is limited to the requested member ID.
Dialogs, downloads, popups, page script errors, and document/stylesheet HTTP errors
stop the run. Unexpected targets and non-lookup/risky controls are blocked.
This policy is intentionally specific to the local read-only portal, not a generic
browser security sandbox. Keep it pointed at the fake-data app.

Each live invocation creates `evidence/discovery-<id>/steps.jsonl`, including
UTC timestamps, step numbers, known routes and controls, actions, outcomes,
redacted output keys, and successful model-response IDs/token usage.
Free-form model reasons are not persisted: a code-generated operational reason
is stored and explicitly labeled as such. Member IDs, balances, names, typed
values, URL queries, raw page text, raw screenshots, prompts, and API keys are
not persisted by this logger. Raw outputs are printed to the caller on completion;
do not redirect them into a public evidence file containing real data.

Failures also produce `failure-dom.json`, a sanitized structural DOM summary
with known visible controls/counts and no arbitrary text. If the browser cannot
start, it records that no snapshot was available. This limited redactor is tailored
to this portal and would need redesign for arbitrary applications.

Runtime evidence is gitignored. Review and deliberately include sanitized genuine
discovery evidence in the eventual submission. No successful live evidence is
fabricated or bundled here. `store=False` is sent to the model API; this is not a
claim of zero retention by the provider.

## Tests and troubleshooting

Offline tests:

```bash
python -m unittest discover -s tests -v
```

Opt-in adapter integration checks (live browser and portal, scripted test decisions,
no API calls, temporary test logs; not discovery evidence):

```bash
RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -v
```

Existing application regression test:

```bash
python verify_portal.py --headed --slow-mo 1000
```

- `BROWSER_LAUNCH_FAILED`: run from your normal terminal; ensure Chromium is installed.
- `MODEL_AUTHENTICATION_FAILED`: check the key in the same terminal.
- `MODEL_RATE_LIMIT_OR_QUOTA`: check API quota/billing or retry later.
- `MODEL_NOT_FOUND` / `MODEL_PERMISSION_DENIED`: select a model available to your API project.
- `MODEL_REQUEST_REJECTED`: confirm the model supports images and Structured Outputs.
- `ENTRY_PAGE_FAILED` / `HTTP_ERROR`: verify that the portal is running and regression checks pass.
- `REPEATED_FAILURE`, `REPEATED_ACTION`, `MAX_STEPS`: inspect redacted steps and failure snapshot.

## Deliberate next-stage cuts

No reusable capability artifact, replay engine, human takeover, expanded target
workflow, tenant infrastructure, or final assignment REPORT.md is included yet.
The current run closes its browser at completion/failure. Real human handoff will
require a session owner with explicit pause/resume and captured manual actions.
Step 3 is not considered demonstrated until genuine LLM runs for 12345 and 99999
have completed and their evidence has been reviewed.

## Subsequent verification and Step 4

The user completed genuine local Qwen runs for 12345, 54321, and 99999; their saved logs were inspected during Step 4. The earlier development-environment limitations above describe that session, not the user's successful terminal runs. Step 4 now records parameter references after successful actions and compiles capabilities; see STEP4.md. Replay and human handoff are still pending.
