"""Offline fixture validation and explicit real-model longitudinal evaluation."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

from becoming.agent import Agent
from becoming.memory import SQLiteConversationStore
from becoming.models import ModelError, OpenAICompatibleModel
from becoming.personal_understanding import PersonalUnderstanding

FIXTURE = Path(__file__).with_name("personal_understanding_cases.json")


class BudgetedModel:
    def __init__(self, model, limit: int):
        self.model = model
        self.limit = limit
        self.calls = 0
        self.timings = []

    def complete(self, messages):
        if self.calls >= self.limit:
            raise ModelError("personal-understanding evaluation call budget exhausted")
        self.calls += 1
        started = time.monotonic()
        try:
            return self.model.complete(messages)
        finally:
            self.timings.append(round(time.monotonic() - started, 3))


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def validate_fixture(data=None):
    data = data or load_fixture()
    turns = data.get("turns")
    if data.get("fictional") is not True or not isinstance(turns, list) or len(turns) != 30:
        raise ValueError("expected the 30-turn fictional longitudinal fixture")
    previous = ""
    labels = set()
    for turn in turns:
        day, text = turn.get("day"), turn.get("text")
        if not isinstance(day, str) or day <= previous or not isinstance(text, str) or not text.strip():
            raise ValueError("turns must have increasing dates and non-empty user text")
        previous = day
        evidence = turn.get("evidence", [])
        if turn.get("no_write") and evidence:
            raise ValueError("no_write turn contains expected evidence")
        for item in evidence:
            if item.get("label") in labels or not item.get("label"):
                raise ValueError("evidence labels must be unique")
            labels.add(item["label"])
            if not item.get("quote") or item["quote"] not in text:
                raise ValueError("expected evidence must be source-bound")
    if len(data.get("expected_understandings", [])) < 5:
        raise ValueError("missing expected understanding review notes")
    if len(data.get("review_criteria", [])) < 8:
        raise ValueError("missing human review criteria")
    return {"turns": len(turns), "evidence_labels": len(labels),
            "review_criteria": len(data["review_criteria"])}


def run_live(max_calls: int, output: str | None = None):
    required = ("BECOMING_BASE_URL", "BECOMING_API_KEY", "BECOMING_MODEL")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise SystemExit("Missing model configuration: " + ", ".join(missing))
    fixture = load_fixture()
    validation = validate_fixture(fixture)
    base = OpenAICompatibleModel(
        os.environ["BECOMING_BASE_URL"], os.environ["BECOMING_API_KEY"],
        os.environ["BECOMING_MODEL"],
    )
    model = BudgetedModel(base, max_calls)

    dynamic_store = SQLiteConversationStore(":memory:")
    dynamic_understanding = PersonalUnderstanding(dynamic_store, model)
    dynamic_agent = Agent(
        model, dynamic_store, history_turns=0,
        personal_understanding=dynamic_understanding,
    )
    dynamic_turns = []
    for item in fixture["turns"][:-1]:
        record = {"day": item["day"], "user": item["text"]}
        try:
            record["assistant"] = dynamic_agent.reply(item["text"])
            record["understanding_event"] = asdict(dynamic_agent.last_understanding_event)
        except (ModelError, ValueError, OSError) as exc:
            record["error"] = type(exc).__name__
            dynamic_turns.append(record)
            break
        dynamic_turns.append(record)

    flush_event = asdict(dynamic_agent.flush_personal_understanding())
    final_user = fixture["turns"][-1]["text"]
    dynamic_final = None
    try:
        dynamic_final = dynamic_agent.reply(final_user)
        final_event = asdict(dynamic_agent.last_understanding_event)
    except (ModelError, ValueError, OSError) as exc:
        final_event = {"error": type(exc).__name__}
    final_flush = asdict(dynamic_agent.flush_personal_understanding())

    claims = []
    for claim in dynamic_understanding.list_claims():
        claims.append({
            "claim": asdict(claim),
            "history": dynamic_understanding.get_claim_history(claim.id),
            "revisions": dynamic_understanding.list_revisions(claim.id),
        })

    # Baseline has the same zero-turn recent-history window, but no persistent
    # personal-understanding context. Only the final synthesis request is needed.
    baseline_store = SQLiteConversationStore(":memory:")
    baseline_agent = Agent(model, baseline_store, history_turns=0)
    baseline_final = None
    try:
        baseline_final = baseline_agent.reply(final_user)
    except (ModelError, ValueError, OSError) as exc:
        baseline_final = "[baseline error: " + type(exc).__name__ + "]"

    report = {
        "fixture": fixture["id"],
        "fictional_data_only": True,
        "validation": validation,
        "model": os.environ["BECOMING_MODEL"],
        "max_calls": max_calls,
        "model_calls": model.calls,
        "call_durations_seconds": model.timings,
        "dynamic": {
            "turns": dynamic_turns,
            "pre_final_flush": flush_event,
            "final_user": final_user,
            "final_answer": dynamic_final,
            "final_event": final_event,
            "post_final_flush": final_flush,
            "active_claims": claims,
        },
        "baseline": {"recent_history_turns": 0, "final_answer": baseline_final},
        "expected_understandings_for_human_review": fixture["expected_understandings"],
        "review_criteria": fixture["review_criteria"],
        "automatic_quality_verdict": None,
        "limitations": [
            "本报告只提供真实模型对话、结构化事件和数据库证据，不自动判定语义质量。",
            "基线与动态组的最终问题使用相同的零轮近期历史窗口；基线不重放历史对话。",
            "单次模型运行不能证明稳定性，必须人工逐轮检查证据、修订、检索和回答。",
        ],
    }
    dynamic_store.close()
    baseline_store.close()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")
        print("Report written to " + str(destination))
    print("Fixture:", fixture["id"])
    print("Turns:", validation["turns"])
    print("Model calls:", model.calls, "/", max_calls)
    print("Active claims:", len(claims))
    print("Dynamic final answer:", dynamic_final or "[not completed]")
    print("Baseline final answer:", baseline_final or "[not completed]")
    print("No automatic quality verdict; inspect the JSON report manually.")
    return report


def main():
    parser = argparse.ArgumentParser(description="Personal understanding longitudinal evaluation")
    parser.add_argument("--live", action="store_true", help="Run the fictional scenario against a real model")
    parser.add_argument("--max-calls", type=int, default=80)
    parser.add_argument("--output", default="artifacts/personal-understanding-live.json")
    args = parser.parse_args()
    if args.max_calls < 1 or args.max_calls > 200:
        parser.error("--max-calls must be between 1 and 200")
    if not args.live:
        print("Personal understanding fixture:", validate_fixture())
        print("Offline validation only; no model calls or quality verdict.")
        return 0
    run_live(args.max_calls, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
