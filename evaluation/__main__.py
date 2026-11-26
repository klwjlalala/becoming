"""Minimal effect evaluation: list cases offline; run one case only with --live.

The displayed criteria are for manual review. No automatic score or pass verdict.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.long_memory import LongMemory
from becoming.models import ModelError, OpenAICompatibleModel


def load_cases():
    cases = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    seen = set()
    if not isinstance(cases, list) or not cases:
        raise ValueError("Expected nonempty list of cases")
    for case in cases:
        if not isinstance(case, dict) or not all(isinstance(case.get(k), str) and case[k].strip()
                                                 for k in ("id", "title")):
            raise ValueError("Invalid case id or title")
        if case["id"] in seen:
            raise ValueError("Duplicate case id")
        seen.add(case["id"])
        if "long_memory" in case and not isinstance(case["long_memory"], bool):
            raise ValueError("Invalid long_memory flag")
        for key in ("turns", "criteria"):
            values = case.get(key)
            if not isinstance(values, list) or not values or not all(
                isinstance(v, str) and v.strip() for v in values
            ):
                raise ValueError(f"Invalid {key}")
    return cases


def main():
    parser = argparse.ArgumentParser(description="Becoming agent effect evaluation")
    parser.add_argument("--live", action="store_true", help="Explicitly call real model")
    parser.add_argument("--case", help="Run exactly one case ID")
    args = parser.parse_args()
    cases = load_cases()
    if not args.live:
        if args.case:
            parser.error("--case requires --live")
        for case in cases:
            print(f"{case['id']}: {case['title']}")
        print("Cases validated. No model calls; no quality evaluation performed.")
        return 0
    case = next((c for c in cases if c["id"] == args.case), None)
    if case is None:
        parser.error("--live requires a valid --case ID")
    try:
        model = OpenAICompatibleModel(
            os.environ.get("BECOMING_BASE_URL", ""),
            os.environ.get("BECOMING_API_KEY", ""),
            os.environ.get("BECOMING_MODEL", ""),
        )
        store = SQLiteConversationStore(":memory:")
        try:
            memory = LongMemory(store, model) if case.get("long_memory") else None
            agent = Agent(model, store, history_turns=0 if memory else 12, long_memory=memory)
            print(f"Case: {case['id']} {case['title']}")
            for turn in case["turns"]:
                print("User:", turn)
                print("Agent:", agent.reply(turn))
                if memory is not None:
                    print("Memory event:", agent.last_memory_event)
            if memory is not None:
                print("Active memories:", memory.list_active())
            print("Manual review criteria:")
            for criterion in case["criteria"]:
                print("-", criterion)
            print("Status: awaiting manual review (not a quality pass).")
        finally:
            store.close()
    except (ValueError, ModelError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
