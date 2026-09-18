# Architecture

The implemented target is a local, read-only Member Service Portal with fictional data. A user supplies a savings-balance goal. Discovery observes the browser, asks a model for a typed action, applies policy, executes through Playwright, and verifies the result. It uses the rendered UI, not application-data imports or a private data API. The recorded discovery runs used local Ollama with qwen3-vl:4b-instruct on an M3 Pro with 18 GB memory. An optional OpenAI adapter exists but was not used for the supplied evidence.

Discovery, compilation, and replay are separate entry points. The compiler transforms supported successful and not-found traces into a strict JSON capability. Replay binds a new member ID and executes that artifact without importing or calling a model. Each replay owns one browser context and page; human intervention retains both. This is a single-process demonstration, without queues or deployment infrastructure.

# Artifact schema

The versioned capability defines typed inputs and outputs, an entry path, ordered actions, parameter references, an outcome checkpoint, and provenance. The runtime policy controls allowed origins independently of the artifact. Inputs remain strings to preserve leading zeros. Outputs include the verified member ID and displayed savings balance. Semantic targets use accessible roles and names or definition-list labels.

The compiler preserves the demonstrated submission method and turns policy-bound input into a parameter reference. A separate not-found trace supports the business-outcome branch. It accepts a deliberately narrow clean trace shape: five successful actions and three not-found actions, with compatible submission methods. It rejects unsupported exploration and failed traces rather than synthesizing missing steps. The portal-specific output contract and branch semantics are authored constraints, not claims of general workflow learning.

The original supplied logs predate explicit parameter-reference events. Rebuilding them requires the explicit legacy-policy-binding flag and relies on the historical executor restricting typed input to the requested member. New logs record references directly. Source hashes make the chosen inputs reproducible; they do not prove a run's authenticity by themselves.

# Determinism & error handling

Replay resolves unique visible semantic targets, waits for supported outcomes, verifies the requested identity, and reads the current displayed balance. It never substitutes a saved balance. The definition-list reader is an adapter for this portal. Ambiguous or missing targets stop execution rather than selecting an arbitrary match.

Results distinguish success, the normal MEMBER_NOT_FOUND business outcome, and technical failures. Timeouts are bounded. Initial navigation has one bounded timeout retry; submission is not blindly repeated. Invalid input and disallowed origins fail before browser launch. Request interception blocks disallowed destinations and non-GET requests before dispatch. Known recoverable errors may escalate when enabled; policy violations are hard stops.

Redacted JSONL records steps, checkpoints, outcomes, and intervention events. Failure snapshots omit sensitive content and explicitly report when no browser was available. Offline tests exercise schema rejection, compilation, verification, request blocking, and handoff edges. The reviewed bundle separately contains actual model and browser runs. Fresh installation and 53 passing offline tests were verified; two opt-in browser tests were skipped because browser launch is blocked in the assistant sandbox.

# Heterogeneity & multi-tenant

The current implementation covers one semantic web portal. A broader design would keep observation, action execution, and output reading behind surface adapters, while retaining typed capabilities and runtime policy. Legacy web frames, image-based targets, and native desktop applications need new target variants and adapter-specific verification; they are not implemented here.

For multiple tenants, capability versions should identify the vendor and supported UI version, while tenant configuration supplies reviewed origins and label mappings. Configuration must not weaken the runtime allowlist. Drift should fail a checkpoint and quarantine the incompatible artifact for reviewed rediscovery. Automatic model-based repair during deterministic replay would change its trust and reproducibility properties and is deliberately absent.

# Escalation & handoff

With human-handoff enabled, supported recoverable blocks can transfer ownership to a human. The explicit demo-handoff option simulates an interruption before lookup; it does not represent an observed portal outage. The terminal explains the requested manual action. Automation pauses while the human operates the same page and context, then accepts resume or abort.

Resume checks the current page and requested member through the real outcome verifier. A wrong-member page is rejected, and policy plus pending runtime errors are checked again before ownership returns to automation. Output collection resumes from the read-only outcome checkpoint. This strategy is appropriate for the demonstrated lookup; write workflows would require explicit commit-state and idempotency handling.

Interventions and time budgets are bounded, with manual time included in the overall run budget. The recorded successful handoff contains 12 redacted manual-action events and ownership transfers in both directions. Captured page events are an audit aid, not a complete recording of browser chrome or operating-system activity. Abort and rejected resume have automated coverage; their final interactive checks remain listed in the demo guide. Discovery itself currently stops on errors rather than providing this replay handoff path.

# Safety

The policy restricts origins, paths, actions, and known read-only controls. Automated typing is restricted to the requested member ID, and extraction to supported fields. Browser service workers are blocked and request interception remains active during handoff. The policy is designed for this controlled portal, not as a general security boundary for arbitrary hostile web content.

Evidence logging removes typed and extracted values, replaces model prose with operational codes, and does not persist screenshots. Discovery can send screenshot and page context to its configured model: the demonstrated provider is local Ollama, while choosing a remote provider changes that data boundary. Terminal result JSON and portal access logs are outside evidence redaction. All demonstration data is fictional.

Runtime evidence is ignored by version control by default. Only reviewed copies under evidence/submission are intended for publication. Original logs are preserved, and the bundle includes a hash manifest. Credentials, environments, and arbitrary new run directories should not be added to the repository.

# Cuts

This submission implements one short read-only lookup, not a universal computer-use agent. It omits transactions, authentication recovery, native desktop execution, tenant provisioning, concurrent workers, and automatic natural-language query routing. A new member ID already reuses the same parameterized artifact; it does not require rediscovery.

Future work is an automatic capability selector: match a request to a registered, compatible capability, validate its parameters, and replay it without model calls. For example, savings lookups for 12345 and 54321 use the same artifact. If no capability matches, an authorized, supported workflow could enter Ollama-driven discovery, followed by compilation and validation before registration for reuse. Ambiguous or unsupported requests should ask for clarification or stop; a replay failure should not silently trigger rediscovery. This routing layer is proposed, not implemented, and would need separate tests for matching, parameter validation, version compatibility, and failed discovery.

The compiler can reject a model run that reaches the right answer through an unsupported action sequence. General trace normalization needs stronger intermediate-state and safety proofs. The next useful verification is an interactive wrong-member rejection and abort, followed by a genuinely injected recoverable portal failure. Supplied live success evidence and mock-based edge tests are kept distinct. Repository publication and submission delivery are separate final actions.
