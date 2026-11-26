"""Unified Becoming companion CLI: conversation, memory and optional growth tools."""
import argparse
import os
import secrets
import sqlite3
import sys
from pathlib import Path

from .agent import Agent
from .memory import SQLiteConversationStore
from .long_memory import LongMemory
from .personal_understanding import PersonalUnderstanding
from .memory_search import ComprehensiveMemory
from .memory_improved import ImprovedMemory
from .embeddings import OpenAICompatibleEmbedder
from .growth_agent import GrowthAgent
from .growth_store import GrowthStore
from .models import DemoModel, OpenAICompatibleModel, ModelError


def main() -> int:
    parser = argparse.ArgumentParser(description="Becoming AI companion")
    parser.add_argument("--demo", action="store_true", help="Offline mock model")
    parser.add_argument("--db", default=None, help="Conversation and long-memory SQLite file")
    parser.add_argument("--growth", action="store_true", help="Enable personal growth tools")
    parser.add_argument("--growth-db", default=None, help="Separate growth SQLite file")
    parser.add_argument("--long-memory", action="store_true", help="Opt in to model-based long-term memory")
    parser.add_argument("--personal-understanding", action="store_true",
                        help="Opt in to evidence-backed, revisable personal understanding")
    parser.add_argument("--semantic-memory", action="store_true", help="Opt in to an extra model call for memory selection")
    parser.add_argument("--comprehensive-memory", action="store_true", help="Opt in to dated multi-topic memory retrieval")
    parser.add_argument("--improved-memory", action="store_true", help="Experimental bounded semantic scan")
    parser.add_argument("--embedding-memory", action="store_true", help="Experimental configured embedding recall")
    args = parser.parse_args()
    if args.growth_db and not args.growth:
        parser.error("--growth-db requires --growth")
    if args.improved_memory and not args.comprehensive_memory:
        parser.error("--improved-memory requires --comprehensive-memory")
    if args.embedding_memory and not args.improved_memory:
        parser.error("--embedding-memory requires --improved-memory")
    if args.comprehensive_memory and (not args.long_memory or args.semantic_memory):
        parser.error("--comprehensive-memory requires --long-memory and replaces --semantic-memory")
    if args.semantic_memory and not args.long_memory:
        parser.error("--semantic-memory requires --long-memory")
    if args.demo and args.long_memory:
        parser.error("--long-memory requires a real model")
    if args.demo and args.personal_understanding:
        parser.error("--personal-understanding requires a real model")

    db_path = args.db if args.db is not None else (
        "data/demo.sqlite3" if args.demo else "data/conversations.sqlite3")
    growth_path = args.growth_db or "data/growth.sqlite3"
    if args.growth and db_path != ":memory:" and growth_path != ":memory:":
        if Path(db_path).resolve() == Path(growth_path).resolve():
            parser.error("Conversation and growth databases must be separate")

    try:
        model = DemoModel() if args.demo else OpenAICompatibleModel(
            os.environ.get("BECOMING_BASE_URL", "https://api.openai.com/v1"),
            os.environ.get("BECOMING_API_KEY", ""),
            os.environ.get("BECOMING_MODEL", ""),
        )
        embedder = (OpenAICompatibleEmbedder(
            os.environ.get("BECOMING_BASE_URL", "https://api.openai.com/v1"),
            os.environ.get("BECOMING_API_KEY", ""),
            os.environ.get("BECOMING_EMBEDDING_MODEL", "")) if args.embedding_memory else None)
        store = SQLiteConversationStore(db_path)
        growth = GrowthStore(growth_path) if args.growth else None
        understanding = PersonalUnderstanding(store, model) if args.personal_understanding else None
    except (ValueError, OSError, sqlite3.Error) as exc:
        if "store" in locals():
            store.close()
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1

    try:
        memory = (ImprovedMemory(store, model, embedder=embedder) if args.improved_memory else
                  ComprehensiveMemory(store, model) if args.comprehensive_memory else
                  LongMemory(store, model, semantic=args.semantic_memory)) if args.long_memory else None
    except sqlite3.Error as exc:
        if growth is not None:
            growth.close()
        store.close()
        print(f"Memory startup failed: {exc}", file=sys.stderr)
        return 1

    agent = (GrowthAgent(model, store, growth, long_memory=memory,
                         personal_understanding=understanding)
             if growth is not None else Agent(model, store, long_memory=memory,
                                              personal_understanding=understanding))
    print("Becoming | " + ("离线模拟" if args.demo else "真实模型（输入及选中的历史资料会发送到配置服务）"))
    print("/exit 退出 | /clear 清除对话及关联长期记忆")
    if growth is not None:
        print("成长辅助已启用；成长记录保存在独立数据库。")
        print("/confirm <token> 确认变更 | /cancel 取消 | /clear-growth 清除全部成长记录（需二次确认）")
        print("清除对话不会删除成长记录；删除成长记录不会清除对话或长期记忆中的副本。")
    if understanding is not None:
        print("动态个人理解已启用：重要纠正即时处理，普通证据最多每 5 轮批量分析；相关证据可能随请求发送。")
    if memory is not None:
        print("长期记忆已启用：每轮回复后会额外调用模型提取；相关历史原话可能随请求发送。")
        if args.improved_memory:
            print("实验检索：最多160条历史分批筛选；向量实验另行启用。")
        if args.embedding_memory:
            print("向量实验已启用：查询与候选原话会发送到配置服务的 embeddings 接口，失败回退分批筛选。")
        if args.comprehensive_memory and not args.improved_memory:
            print("综合检索已启用：最多增加两次模型调用（检索条件解析与有限历史候选筛选）。记录日期按 UTC。")
        if args.semantic_memory:
            print("语义检索已启用：最多40条候选原话发送给模型做筛选，增加一次模型调用。")
        print("/memories 查看 | /forget <key> 删除并阻止同槽位重新写入 | /allow <key> 恢复未来写入")
        print("删除记忆不删除原始对话；/clear 清除对话与关联长期记忆，保留阻止写入的槽位名称。")

    pending_growth_clear = None
    understanding_flushed = False
    try:
        while True:
            text = input("你：").strip()
            if text == "/exit":
                if growth is not None:
                    agent.reply("/cancel")
                if understanding is not None:
                    event = agent.flush_personal_understanding()
                    understanding_flushed = True
                    if event.errors:
                        print("Personal understanding warning: " + ", ".join(event.errors), file=sys.stderr)
                break
            if text == "/clear-growth":
                if growth is None:
                    print("请使用 --growth 启用成长辅助。")
                else:
                    agent.reply("/cancel")
                    pending_growth_clear = secrets.token_hex(4)
                    print("这将删除全部成长目标、行动和复盘，但不会删除对话或长期记忆副本。")
                    print("如确认，请输入 /confirm-growth-clear " + pending_growth_clear + "。")
                continue
            if text.startswith("/confirm-growth-clear "):
                token = text[len("/confirm-growth-clear "):].strip()
                if growth is None or pending_growth_clear is None or token != pending_growth_clear:
                    print("没有匹配的成长数据清除确认。")
                else:
                    pending_growth_clear = None
                    counts = growth.clear()
                    try:
                        store.append_turn("我确认清除全部成长记录。",
                                          "已清除成长记录：" + str(counts))
                        print("成长记录已清除：" + str(counts))
                    except sqlite3.Error:
                        print("成长记录已清除，但对话审计记录未能写入：" + str(counts), file=sys.stderr)
                continue
            if pending_growth_clear is not None:
                pending_growth_clear = None

            is_memory_command = (text in ("/clear", "/memories") or
                                 text == "/forget" or text.startswith("/forget ") or
                                 text == "/allow" or text.startswith("/allow "))
            if growth is not None and is_memory_command:
                agent.reply("/cancel")  # memory commands must not leave a stale growth proposal alive
            if text == "/clear":
                store.clear()
                print("对话历史及其关联长期记忆、个人理解证据已清除（逻辑删除）。")
                if growth is not None:
                    print("独立成长记录仍保留；如需清除请使用 /clear-growth。")
                continue
            if memory is not None and text == "/memories":
                for item in memory.list_active():
                    print(f"{item.key} [{item.category}] #{item.source_turn_id}: {item.quote}")
                for key in memory.blocked_keys():
                    print(f"{key} [已阻止写入]")
                continue
            if memory is not None and (text == "/forget" or text.startswith("/forget ")):
                key = text[len("/forget"):].strip()
                if not key:
                    print("用法：/forget <key>")
                else:
                    try:
                        count = memory.forget(key)
                        print(f"已逻辑删除 {count} 条记忆修订并阻止同槽位写入；原始对话仍保留。")
                    except ValueError as exc:
                        print(f"Error: {exc}", file=sys.stderr)
                continue
            if memory is not None and (text == "/allow" or text.startswith("/allow ")):
                try:
                    changed = memory.allow(text[len("/allow"):].strip())
                    print("允许未来写入，旧数据不会恢复。" if changed else "该槽位未被阻止。")
                except ValueError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                continue
            if not text:
                continue
            try:
                print("Becoming：" + agent.reply(text))
                memory_event = agent.last_memory_event
                if memory_event.errors:
                    print("Memory warning: " + ", ".join(memory_event.errors), file=sys.stderr)
                understanding_event = agent.last_understanding_event
                if understanding_event.errors:
                    print("Personal understanding warning: " + ", ".join(understanding_event.errors), file=sys.stderr)
                if growth is not None and agent.last_event and agent.last_event.get("status") in ("rejected", "failed"):
                    print("Growth tool warning: " + agent.last_event["status"], file=sys.stderr)
            except (ModelError, ValueError, sqlite3.Error) as exc:
                print(f"Error: {exc}", file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        print()
    except sqlite3.Error as exc:
        print(f"Storage error: {exc}", file=sys.stderr)
        return 1
    finally:
        if understanding is not None and not understanding_flushed:
            try:
                event = agent.flush_personal_understanding()
                if event.errors:
                    print("Personal understanding warning: " + ", ".join(event.errors), file=sys.stderr)
            except (sqlite3.Error, ValueError, ModelError):
                print("Personal understanding warning: flush_failed", file=sys.stderr)
        if growth is not None:
            growth.close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
