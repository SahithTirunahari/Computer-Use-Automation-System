# Demo guide

Allow 6–8 minutes, plus variable local-model inference time. Start the portal and activate the environment using README.md. Keep the terminal and automation browser visible.

1. **Explain the goal.** “I learn a supported read-only workflow once, compile it into a typed artifact, and replay it with different inputs without a model.” Show the fictional portal.
2. **Show discovery.** Follow the discovery commands in README.md with Ollama running. Explain observation, typed action proposals, policy checks, and verification. If time is short, show the supplied recorded logs and clearly call them previously recorded runs.
3. **Show the artifact.** Rebuild from the supplied logs using the README command. Show the member-ID parameter reference, semantic targets, outcome checkpoint, output contract, and provenance. Explain the explicit legacy migration flag.
4. **Demonstrate model-free replay.** Quit Ollama, keep the portal running, and run the commands below. Show the different balance and the normal not-found result.

```bash
python -m replay --member-id 54321 --headed --slow-mo 1000
python -m replay --member-id 99999 --headed --slow-mo 1000
```

5. **Demonstrate human control.** Run the command below. Explain that the interruption is intentionally simulated, while manual control and resume verification are real. Search for 12345 in the browser opened by the runner, then type `resume` in its terminal.

```bash
python -m replay --member-id 12345 --headed --demo-handoff --timeout 300
```

6. **Show evidence and limitations.** Open the resulting steps.jsonl: ownership transfer, redacted manual events, verification, result. Explain that this is one semantic portal and that desktop/multi-tenant support is a design, not a completed feature.

## Future work talking point

“The next extension would automatically select an existing capability for a
request. A savings lookup for a different member would reuse the same artifact
with a new parameter and no model calls. If no compatible capability exists,
an authorized, supported workflow could use Ollama for discovery, then compile
and validate the new artifact before making it reusable. Ambiguous requests
would need clarification, and replay failures would not silently trigger
rediscovery. This selector is future work; the current demo selects the
capability explicitly.”

## Final interactive checks

These complement automated tests and should be performed before submission:

- **Rejected resume:** start the handoff command for 12345, manually search for 54321, and type `resume`. It must reject the page. Return to search, find 12345, and resume successfully.
- **Abort:** start a new handoff run and type `abort`. Confirm a failure result and browser cleanup.
- **Disallowed origin:** run `python -m replay --member-id 12345 --url http://example.invalid`. It must reject the URL before browser launch.

Keep each run's evidence path. Review any new logs before adding them to the submission bundle; do not label offline test output as a live browser recording.

## Before publishing

Run the README test commands, review REPORT.md, and confirm only fictional data and reviewed evidence are included. Exclude `.venv`, `.env` files, generated caches, and unreviewed runtime evidence. Create the public repository and supply its URL only when ready to publish. No repository has been published or submission email sent by this preparation step.
