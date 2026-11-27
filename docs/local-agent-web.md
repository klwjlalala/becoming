# Node agent migration — revised scope

The main branch remains the reference implementation. The current development branch is intentionally local-first and single-user. Python is ONLY a stateless LLM forwarding service; no account, billing, server DB, sync, payments or new growth features in this phase. Never expose the unauthenticated development gateway to the public Internet.

## Run (Python 3.11+, Node 22.13+)

From repository root, terminal 1:

    python -m pip install -e .
    export BECOMING_BASE_URL=https://api.openai.com/v1
    export BECOMING_API_KEY=your-provider-key
    export BECOMING_MODEL=your-model
    python -m uvicorn server.app:app --host 127.0.0.1 --port 8000

Terminal 2:

    npm --prefix agent-runtime start

Open http://127.0.0.1:4310. Configure the provider only in Python. The Node gateway adapter receives text; usage returned by the provider is passed through without storing or calculating fees. Local SQLite defaults to data/agent-local.sqlite3 (new database, not an in-place migration of the Python schema). Web remains a plain conversation page with background status.

## Migration checkpoint

- Ported: conversation history, companion/self-exploration/guidance system prompts, default lexical long-memory retrieval, optional V1 semantic selection, source-quote validation, credential guard, slot dedupe/revision, exact-slot forget/allow, idempotent receipts, atomic turn+job enqueue, finite background retries and startup recovery.
- Personal understanding migration: original schema/policies, proposal reference validation, evidence, claim versions, revision operations, confirmation handling, retrieval, durable internal jobs, and source-deletion trigger are now wired into the runtime. Complete parity with the original Python evaluation and regression suite is NOT established.
- Not yet ported: complete regression parity. These are existing capabilities, not authorization to add new business functionality. No real-model quality pass is claimed.
- This checkpoint uses single-process/multi-conversation Node; previous prototype's sync code and server DB have been removed from the active runtime. Legacy Python packages/tests remain as behavioral references.
- Tests: npm --prefix agent-runtime test; python -m pip install httpx; python -m unittest server.test_gateway -v; python server/smoke_local.py. HTTP smoke uses a local fake upstream provider, not paid inference.

Existing growth tools are restored in the Node runtime using the original tool prompt and a separate local SQLite DB. Mutations require a session-bound, one-use confirmation; the simple browser page exposes confirm/cancel and conversation selection, not a new growth management UI. Conversation history is isolated; memory and understanding remain user-level. Pending confirmations do not survive process restart. This is not a migration of existing Python DB files.

Memory retrieval mode is explicit: BECOMING_MEMORY_MODE=lexical (original API default), semantic, historical, or improved. Historical mode includes date-filtered historical evidence and bounded diverse candidate selection. Improved mode includes conservative revision validation and multi-batch ranking; optional embedding forwarding uses BECOMING_ENABLE_EMBEDDINGS=1 on Node and BECOMING_EMBEDDING_MODEL on Python. No vectors are persisted. Python still owns only model forwarding, including optional embeddings; it has no agent or billing logic. 

## Acceptance (separate functional and effect suites)

- Offline: npm --prefix agent-runtime test and npm --prefix agent-runtime run test:effects (fixture validation only). The original Python tests remain the comparison baseline, not proof of Node parity.
- Real-model explicit capability checks: start the Python gateway with real provider configuration, then npm --prefix agent-runtime run test:live. Uses isolated in-memory SQLite, fictional data, max 36 LLM calls, asserts DB writes, all seven growth tools, revisions and actual recalled IDs. Fails nonzero on assertion errors.
- Natural scenarios: BECOMING_EFFECT_MODE=scenarios npm --prefix agent-runtime run evaluate:live. Longitudinal: BECOMING_EFFECT_MODE=longitudinal npm --prefix agent-runtime run evaluate:live. Both reuse original fixtures, report actual turns, jobs, evidence and claims; no automatic quality verdict. Longitudinal uses production async job path drained after each turn and equal zero-turn recent history for the final baseline, simulated fixture dates, max 70 calls (not directly identical to the original Python CLI batching schedule).
- GitHub Actions Node agent real-model acceptance uses existing repository model secrets, explicit suite selection, no secret output, synthetic report artifacts. One exact commit message triggers the initial functional run; future routine pushes do not consume live model quota. The other suites require manual dispatch on the migration branch.

### Real-model acceptance diagnostics
The first two runs intentionally used synthetic databases, but incorrectly described positive memory/understanding statements as fictional inside the simulated user message. The model appropriately returned empty proposals. Positive fixtures now present ordinary first-person facts; the test harness, not the user message, marks all inputs as synthetic. The runtime's privacy and hypothetical-statement policy is unchanged. The legacy growth preview parser accepts only a recognized preview label and known snapshot fields; it discards model-generated snapshots, builds a fresh DB preview, and still requires one-time user confirmation. Regression tests cover forged snapshots and invalid approval fields.

Third live functional run (45949840033): memory and understanding passed; growth failed on a short sentence before the legacy preview header. The parser now recognizes either exact header after a bounded explanatory prefix; strict envelope validation, authoritative previews and user confirmation remain. The next one-shot acceptance workflow gates both original effect suites on functional success, runs in sequence, and writes separate synthetic reports (maximum 36 + 80 + 70 model calls). Routine pushes do not trigger model calls. Effect workflow completion is not a semantic quality verdict.
