# Submission preparation verification

Checked on 2026-09-16 using Python 3.13.3 on macOS.

| Check | Result |
| --- | --- |
| Fresh virtual environment; install requirements-agent.txt with constraints-tested.txt | Passed |
| python -m pip check in fresh environment | No broken requirements |
| python -m unittest discover -s tests -q in fresh environment | 55 tests run: 53 passed, 2 opt-in browser tests skipped |
| Compile supplied success/not-found logs with explicit legacy binding | Passed |
| Compare rebuilt artifact against canonical artifact | Byte-for-byte identical |
| Compare ten bundled evidence/artifact files against original files | All identical; SHA-256 recorded in manifest.json |
| Parse every bundled JSONL line | Passed |
| Scan bundled JSONL for demonstration member IDs, names, and balances | No checked fixture values found; this is not a universal PII detector |

Handoff hardening now propagates policy violations and rechecks policy and
pending runtime errors before returning control to automation. Added tests
cover these conditions, wrong-member rejection through the actual outcome
verifier, pre-launch origin validation, and interception of external or
non-GET requests before dispatch.

Previously recorded live evidence covers discovery, successful and not-found
replay, and successful human handoff. These are distinct from offline tests,
which use controlled doubles for browser interaction. Fresh browser execution
could not be verified in the assistant sandbox because Chromium launch was
blocked by macOS sandbox restrictions.

Before publication, perform the interactive rejected-resume and abort checks
in DEMO.md and run the opt-in browser checks in a normal terminal. Public
repository creation and submission delivery have not been performed.
