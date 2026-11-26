"""CLI for offline smoke tests and optional real model conversations."""
import argparse
import os
import sqlite3
import sys

from .agent import Agent
from .memory import SQLiteConversationStore
from .long_memory import LongMemory
from .memory_search import ComprehensiveMemory
from .memory_improved import ImprovedMemory
from .embeddings import OpenAICompatibleEmbedder
from .models import DemoModel, OpenAICompatibleModel, ModelError


def main() -> int:
    parser = argparse.ArgumentParser(description="Becoming AI companion prototype")
    parser.add_argument("--demo", action="store_true", help="Offline mock model")
    parser.add_argument("--db", default=None, help="SQLite file or :memory:")
    parser.add_argument("--long-memory", action="store_true", help="Opt in to model-based long-term memory")
    parser.add_argument("--semantic-memory", action="store_true", help="Opt in to an extra model call for memory selection")
    parser.add_argument("--comprehensive-memory", action="store_true", help="Opt in to dated multi-topic memory retrieval")
    parser.add_argument("--improved-memory", action="store_true", help="Experimental bounded semantic scan")
    parser.add_argument("--embedding-memory", action="store_true", help="Experimental configured embedding recall")
    args = parser.parse_args()
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
    try:
        if args.demo:
            model = DemoModel()
        else:
            model = OpenAICompatibleModel(
                os.environ.get("BECOMING_BASE_URL", "https://api.openai.com/v1"),
                os.environ.get("BECOMING_API_KEY", ""),
                os.environ.get("BECOMING_MODEL", ""),
            )
        embedder = (OpenAICompatibleEmbedder(os.environ.get("BECOMING_BASE_URL", "https://api.openai.com/v1"),
                    os.environ.get("BECOMING_API_KEY", ""), os.environ.get("BECOMING_EMBEDDING_MODEL", ""))
                    if args.embedding_memory else None)
        db_path = args.db if args.db is not None else (
            "data/demo.sqlite3" if args.demo else "data/conversations.sqlite3"
        )
        store = SQLiteConversationStore(db_path)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1

    try:
        memory = (ImprovedMemory(store, model, embedder=embedder) if args.improved_memory else
                  ComprehensiveMemory(store, model) if args.comprehensive_memory else
                  LongMemory(store, model, semantic=args.semantic_memory)) if args.long_memory else None
    except sqlite3.Error as exc:
        store.close()
        print(f"Memory startup failed: {exc}", file=sys.stderr)
        return 1
    agent = Agent(model, store, long_memory=memory)
    print("Becoming | " + ("离线模拟" if args.demo else "真实模型（发送最近对话到配置服务）"))
    print("/exit 退出 | /clear 清除当前对话历史")
    if memory is not None:
        print("长期记忆已启用：每轮回复后额外发送当前输入及有限历史记忆原话；相关记忆可能随回复请求发送。")
        if args.improved_memory:
            print("实验检索：最多160条历史分批筛选；增加模型调用，向量实验另行启用。")
        if args.embedding_memory:
            print("向量实验已启用：查询与候选原话会发送到配置服务的 embeddings 接口，失败回退分批筛选。")
        if args.comprehensive_memory and not args.improved_memory:
            print("综合检索已启用：最多增加两次模型调用（检索条件解析与有限历史候选筛选）。记录日期按 UTC。")
        if args.semantic_memory:
            print("语义检索已启用：最多40条候选原话发送给模型做筛选，增加一次模型调用。")
        print("/memories 查看 | /forget <key> 删除并阻止同槽位重新写入 | /allow <key> 恢复未来写入")
        print("删除记忆不删除原始对话；/clear 清除对话与关联记忆，保留阻止写入的槽位名称。")
    try:
        while True:
            text = input("你：").strip()
            if text == "/exit":
                break
            if text == "/clear":
                store.clear()
                print("对话历史已清除。")
                if memory is not None:
                    print("关联长期记忆已清除（逻辑删除）。")
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
                if agent.last_memory_event.errors:
                    print("Memory warning: " + ", ".join(agent.last_memory_event.errors), file=sys.stderr)
            except (ModelError, ValueError, sqlite3.Error) as exc:
                print(f"Error: {exc}", file=sys.stderr)
    except (EOFError, KeyboardInterrupt):
        print()
    except sqlite3.Error as exc:
        print(f"Storage error: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
