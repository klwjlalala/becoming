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
- Not yet ported: dynamic personal understanding (full evidence/claim/version/revision/confirmation/batch policy), existing confirmed growth tools, multiple conversations, advanced historical/embedding retrieval variants, and complete regression parity. These are existing capabilities, not authorization to add new business functionality. No real-model quality pass is claimed.
- This checkpoint uses single-process/single-conversation Node; previous prototype's sync code and server DB have been removed from the active runtime. Legacy Python packages/tests remain as behavioral references.
- Tests: npm --prefix agent-runtime test; python -m pip install httpx; python -m unittest server.test_gateway -v; python server/smoke_local.py. HTTP smoke uses a local fake upstream provider, not paid inference.
