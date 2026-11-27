# Local Agent Runtime — migration branch

Baseline: 36e7c31b5dfb24b14906458302df356cf4767e6b. This branch replaces the Electron shell with a local Node.js service and browser test page. The existing Python agent and its tests are retained as a behavioral reference, not used by the new runtime.

## Run the first vertical slice

Python 3.11+, Node.js 22.13+ (built-in SQLite). In two terminals from the repository root:

    python -m pip install -e .
    export BECOMING_TOKEN=replace-with-a-long-random-development-token
    export BECOMING_DEMO=1
    python -m uvicorn server.app:app --host 127.0.0.1 --port 8000

    export BECOMING_TOKEN=replace-with-the-same-token
    export BECOMING_SYNC=1
    npm --prefix agent-runtime start

Open http://127.0.0.1:4310 (not localhost). Sync is explicitly enabled by BECOMING_SYNC=1 because transcripts are personal data. Without it, local history still works. Demo mode is explicitly enabled; for real inference unset it and configure BECOMING_MODEL_BASE_URL, BECOMING_MODEL_API_KEY and BECOMING_MODEL on the Python server only. Use a separate development database for demo vs real conversations (BECOMING_LOCAL_DB, BECOMING_SERVER_DB). Account namespace BECOMING_ACCOUNT defaults to dev and must match both processes. Never share a local DB across accounts.

## Scope and decisions

- Node owns prompt construction, conversation history, reply lifecycle, SQLite and independent retrying sync worker. Current migration copies the original companion/exploration/guidance policies; no task/growth UI or additional business functions.
- Python owns gateway authentication, upstream model credentials, measured token usage, optional configured cost (integer microunits per million input/output tokens), cloud SQLite and sync API. It is a single configured development account, not a production registration/session/payment system. Unknown usage is null, uncertain requests are marked uncertain; request IDs are not replayed automatically.
- Append-only sync uses UUID identity, idempotent upload, per-account cursor, atomic local ack/pull and retries; cloud is not on the local persistence path. No automatic data upload unless enabled. Multi-device editing, deletion propagation, encryption, account switching, schema migration and production PostgreSQL are not implemented.
- Web is intentionally a dependency-free same-origin debugging page rather than a Vue product UI, to keep the first verification path small. Runtime binds loopback and rejects other Host/Origin values. No public exposure without a production security design.
- LLM is non-streaming in this slice. Existing long-memory extraction/revision/retrieval, dynamic personal understanding/evidence/confirmation, persistent post-turn jobs and business tool calling have NOT been ported. Do not treat this as parity with main. Migrate memory and personal understanding before product feature work, then replay existing functional/effect evaluation cases against Node.

## Verification

    npm --prefix agent-runtime test
    python -m pip install httpx
    python -m unittest server.test_gateway -v

Real provider tests are opt-in and not part of default CI. No test result is asserted merely by adding tests.
