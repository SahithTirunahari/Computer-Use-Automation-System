# Reviewed submission evidence

These are unchanged copies of recorded runs, not regenerated or synthetic logs.
The manifest lists SHA-256 hashes for the run files and canonical artifact.
Redacted logs deliberately cannot establish the original concrete member ID;
the terminal outputs supplied during development showed the expected balances.

| File or directory | Evidence |
| --- | --- |
| get_savings_balance.v1.json | Typed, parameterized capability; identical to the canonical capabilities/ copy |
| discovery-805b4a7f969f | Real local Ollama discovery, successful lookup; compiler success input |
| discovery-75d349e7911b | Second real local Ollama discovery, successful lookup |
| discovery-cc2eb3e3ac67 | Real local Ollama discovery, normal MEMBER_NOT_FOUND; compiler branch input |
| replay-ff8e3c499ee2 | Recorded deterministic successful replay, model_calls 0 |
| replay-0a5de806ae15 | Second recorded deterministic successful replay, model_calls 0 |
| replay-c3d4344ad11c | Recorded deterministic MEMBER_NOT_FOUND, model_calls 0 |
| replay-c95afda1da1d | Real manual lookup during demo interruption, 12 redacted human actions, verified resume and success |
| replay-2afa8fb12f75 | CLI INVALID_INPUT failure before browser launch; not a browser exception recording |

The handoff interruption was deliberately requested with --demo-handoff. It
demonstrates real same-session human actions and verified resumption, not a
naturally occurring outage. Abort and wrong-member rejection are covered by
offline tests; interactive recordings of those paths are not included.

The compiler rebuild command is in the project README. Hashes detect content
changes but do not attest execution. Runtime logs outside this folder are
excluded from version control. The hash manifest intentionally covers original
evidence files and the artifact, not this explanatory index or the manifest itself.
