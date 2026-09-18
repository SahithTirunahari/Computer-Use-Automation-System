> Historical milestone notes. See [README.md](README.md) and [REPORT.md](REPORT.md) for current behavior and verification status.

# Step 4: Compile discovery into a reusable capability

## What was implemented

1. Added `capabilities/schema.py`: strict Pydantic contracts for versioned inputs,
   outputs, semantic targets, ordered steps, terminal conditions, and provenance.
2. Added `capabilities/compiler.py`: an offline deterministic compiler. It reads
   trusted local discovery logs, validates their executed actions and final results,
   and writes JSON. It does not call Ollama, OpenAI, or a browser.
3. Updated `agent/evidence.py` and `agent/agent.py`: future successful actions also
   emit a `capability_action` event. Typing values become `{"input":"member_id"}`
   only after the runtime policy proves they equal the requested member ID. Raw
   values and model prose are never written into this recording.
4. Compiled `capabilities/get_savings_balance.v1.json` using the genuine successful
   run `discovery-805b4a7f969f` and not-found run `discovery-cc2eb3e3ac67`.
5. Added `tests/test_capabilities.py` for serialization, schema validation, source
   validation, explicit legacy migration, parameter recording, and malformed logs.

The existing portal and hard-coded regression script were not changed. The new
recorder records actions; it does not automatically publish capabilities or replay
anything. Compilation is an explicit local command after a run has finished.

## Artifact behavior

The capability is named `get_savings_balance`, schema version `1.0`, capability
version `1.0.0`. It requires one five-digit string parameter, `member_id`, and
returns strings `member_id` and `savings_balance` on success.

Its exact flow is:

1. Fill the visible Member ID textbox using the input reference.
2. Press Enter on the visible Search button, as observed in the successful run.
3. Wait up to 10 seconds for exactly one supported outcome:
   - Member Details with the displayed Member ID equal to the parameter: continue.
   - Member Not Found with a matching message and URL member parameter: return
     `business_outcome / MEMBER_NOT_FOUND` immediately, with no output values.
   - No supported outcome: fail with `UNEXPECTED_STATE_OR_TIMEOUT`.
   - Both outcomes: fail with `AMBIGUOUS_OUTCOME`.
4. Extract Member ID from its visible definition label.
5. Extract Current Savings Balance from its visible definition label.
6. Apply the terminal success contract: require both outputs, the correct member,
   the declared formats, and a fresh comparison with the live UI.

The sixth item is a terminal contract, not a recorded browser action. Targets must
resolve to exactly one visible match; there is no positional fallback. The runtime
base URL is intentionally absent: the future replay caller supplies it and must
apply the portal policy to that origin plus the artifact's `/` entry path.

The checkpoint and success contract are explicit portal rules supplied by code.
They are not claimed to be learned from a happy-path trace. The separate not-found
run backs the business-outcome rule. Version 1 accepts only the clean type/submit/
extract/extract/done discovery sequence (or type/submit/done for not-found), with
submission by Search click or Enter on Search/Member ID. Recoveries, extra actions,
failed runs, mismatched submissions, and partially recorded runs are rejected.
Future compilers can support more flows without quietly changing this contract.

## Existing logs and explicit migration

Your original discovery runs predate parameter recording. They contain a redacted
value, not an explicit input reference. The initial artifact was therefore compiled
with `--legacy-policy-binding`. This relies on the known historical executor policy:
only the requested member ID could be typed into the Member ID textbox.

The migration is explicit in the command and provenance, and never attempts to
recover the hidden ID. A validation sentinel is used in memory only. This is a
narrow migration for these trusted local runs, not a general inference mechanism
for arbitrary redacted logs. For new runs, the compiler requires the directly
recorded binding and cross-checks it against the executed diagnostic step.

Source-log SHA-256 hashes identify the exact input bytes; they are integrity
references, not cryptographic proof that a log is authentic. Preserve the source
logs for review. They remain gitignored pending deliberate evidence selection.
No recorded ID, name, account number, or balance is embedded in the capability.

## Commands

From the project directory with `.venv` active, the artifact already exists. To
reproduce it at a NEW path from the old logs:

```bash
python -m capabilities.compiler \
  --success-run evidence/discovery-805b4a7f969f/steps.jsonl \
  --not-found-run evidence/discovery-cc2eb3e3ac67/steps.jsonl \
  --legacy-policy-binding \
  --output capabilities/get_savings_balance.rebuilt.json
```

The compiler refuses to overwrite an existing file. Choose a new output path.
To generate input-reference recordings using the updated agent:

```bash
python -m agent --goal "Find the current savings balance for member 12345." --headed --slow-mo 1000
python -m agent --goal "Find the current savings balance for member 99999." --headed --slow-mo 1000
```

Use the resulting evidence directories (substitute their actual names):

```bash
python -m capabilities.compiler \
  --success-run evidence/discovery-<successful-run>/steps.jsonl \
  --not-found-run evidence/discovery-<not-found-run>/steps.jsonl \
  --output capabilities/get_savings_balance.new.json
```

New recordings do not need `--legacy-policy-binding`. Both runs must use the same
submission action; if the model chooses different valid methods, version 1 rejects
that pair rather than silently normalizing them.

Validate the saved artifact:

```bash
python -c 'from pathlib import Path; from capabilities.schema import Capability; c = Capability.model_validate_json(Path("capabilities/get_savings_balance.v1.json").read_text()); print(c.name, c.capability_version, "validated")'
```

Run offline tests:

```bash
python -m unittest discover -s tests -v
```

## Verification and next step

The compiler generated and validated the first artifact from the real saved logs.
The full offline suite passes; the opt-in browser integration test is skipped by
default. Test fixtures are synthetic and temporary, never discovery evidence.

Step 4 defines and validates execution semantics; it does not yet execute them.
Step 5 must implement the artifact interpreter, enforce input/output validation
and policy, evaluate outcome branches, and demonstrate replay for different member
IDs with zero model calls. Human handoff remains a later milestone.
