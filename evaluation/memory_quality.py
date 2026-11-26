"""Longitudinal extraction and retrieval diagnostics; no live calls by default.

Exact-span matches are conservative evidence proxies, not semantic quality scores.
The model never receives expected labels, spans, review criteria or reports.
"""
import argparse
import json
import os
from dataclasses import asdict

from becoming.agent import Agent
from becoming.long_memory import LongMemory
from becoming.memory_search import ComprehensiveMemory
from becoming.memory import SQLiteConversationStore
from becoming.models import ModelError, OpenAICompatibleModel
from evaluation.quality_cases import validate_cases


class DatedStore(SQLiteConversationStore):
    """Test-only clock: stamp completed turns before extraction starts."""
    day = None

    def append_turn(self, user, assistant):
        turn_id = super().append_turn(user, assistant)
        if self.day is not None:
            with self.connection:
                self.connection.execute("UPDATE turns SET created_at=? WHERE id=?",
                                        (self.day + " 12:00:00", turn_id))
        return turn_id


class CountedModel:
    def __init__(self, model):
        self.model = model
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return self.model.complete(messages)


def all_records(store):
    rows = store.connection.execute("""
        SELECT m.id,m.key,m.category,m.quote,m.source_turn_id,t.created_at,m.active
        FROM long_memories m JOIN turns t ON t.id=m.source_turn_id ORDER BY m.id
    """)
    names = ("id", "key", "category", "quote", "source_turn_id", "recorded_at_utc", "active")
    return [dict(zip(names, row)) for row in rows]


def audit(case, turns, records):
    """Locate source-backed spans in persisted history; don't infer equivalent meanings."""
    results = {}
    noise = []
    for turn, trace in zip(case.history, turns, strict=True):
        rows = [r for r in records if r["source_turn_id"] == trace["turn_id"]]
        if turn.no_write and rows:
            noise.append({"turn_id": trace["turn_id"], "ids": [r["id"] for r in rows]})
        for expected in turn.evidence:
            matched = [r for r in rows if expected.span in r["quote"]]
            state_ok = expected.active is None or any(bool(r["active"]) == expected.active for r in matched)
            results[expected.label] = {
                "turn_id": trace["turn_id"], "span": expected.span,
                "matched_ids": [r["id"] for r in matched],
                "expected_active": expected.active,
                "state_check": ("not_specified" if expected.active is None else
                                "matched" if state_ok else "mismatch" if matched else "not_observed"),
            }
    return results, noise


def probe_audit(case, evidence, event):
    selected = set(event.retrieved_ids)
    candidates = None if event.search is None else set(event.search["candidate_ids"])
    details = {}
    for label in case.expected:
        ids = set(evidence[label]["matched_ids"])
        if not ids:
            status = "missing_exact_span_in_storage"
        elif ids & selected:
            status = "selected"
        elif candidates is None:
            status = "not_selected_candidate_trace_unavailable"
        elif not ids & candidates:
            status = "outside_candidate_pool"
        else:
            status = "candidate_not_selected"
        details[label] = status
    return details


def run_case(case, model, *, progress=None):
    model = CountedModel(model)
    store = DatedStore(":memory:")
    try:
        memory = ComprehensiveMemory(store, model)
        agent = Agent(model, store, history_turns=12, long_memory=memory)
        traces = []
        for turn in case.history:
            store.day = turn.day
            before = model.calls
            answer = agent.reply(turn.text)
            turn_id = store.connection.execute("SELECT max(id) FROM turns").fetchone()[0]
            traces.append({"turn_id": turn_id, "day": turn.day, "user": turn.text,
                           "reply": answer, "event": asdict(agent.last_memory_event),
                           "model_calls": model.calls - before})
            if progress:
                progress(len(traces), len(case.history))
        records = all_records(store)
        evidence, noise = audit(case, traces, records)
        probes = {}
        # The history and stored records are identical for every probe; no cross-arm contamination.
        for mode in ("no-memory", "v1.1", "v1.3"):
            branch = DatedStore(":memory:")
            try:
                store.connection.backup(branch.connection)
                branch.day = case.query_day
                mem = (None if mode == "no-memory" else
                       LongMemory(branch, model, semantic=True) if mode == "v1.1" else
                       ComprehensiveMemory(branch, model))
                before = model.calls
                probe = Agent(model, branch, history_turns=0, long_memory=mem)
                reply = probe.reply(case.query)
                event = probe.last_memory_event
                probes[mode] = {"reply": reply, "event": asdict(event),
                                "diagnostics": probe_audit(case, evidence, event),
                                "model_calls": model.calls - before}
            finally:
                branch.close()
        return {"title": case.title, "turns": traces, "records": records, "evidence": evidence,
                "exact_span_matched": sum(bool(v["matched_ids"]) for v in evidence.values()),
                "expected_span_count": len(evidence), "unexpected_write_review": noise,
                "query": case.query, "query_day": case.query_day, "probes": probes,
                "model_calls": model.calls, "criteria": case.criteria,
                "verdict": "awaiting_manual_review"}
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cases = validate_cases()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", choices=cases)
    parser.add_argument("--output", help="Optional JSON report file (fictional test data)")
    args = parser.parse_args()
    if not args.live:
        if args.case or args.output:
            parser.error("--case and --output require --live")
        for key, case in cases.items():
            print(f"{key}: {case.title}; {len(case.history)} history turns")
        print("Fixtures validated; no model calls, no quality verdict.")
        return 0
    if not args.case:
        parser.error("--live requires --case")
    import sys
    from pathlib import Path
    try:
        model = OpenAICompatibleModel(os.environ.get("BECOMING_BASE_URL", ""),
                                      os.environ.get("BECOMING_API_KEY", ""),
                                      os.environ.get("BECOMING_MODEL", ""))
        report = run_case(cases[args.case], model,
                          progress=lambda n, total: print(f"History {n}/{total}", file=sys.stderr))
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(payload + "\n", encoding="utf-8")
        else:
            print(payload)
        print("Exact-span diagnostics are not a semantic quality verdict.", file=sys.stderr)
        return 0
    except (ValueError, ModelError, OSError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
