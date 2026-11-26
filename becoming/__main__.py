"""CLI for offline smoke tests and optional real model conversations."""
import argparse
import os
import sqlite3
import sys

from .agent import Agent
from .memory import SQLiteConversationStore
from .long_memory import LongMemory
from .models import DemoModel, OpenAICompatibleModel, ModelError


def main() -> int:
    parser = argparse.ArgumentParser(description="Becoming AI companion prototype")
    parser.add_argument("--demo", action="store_true", help="Offline mock model")
    parser.add_argument("--db", default=None, help="SQLite file or :memory:")
    parser.add_argument("--long-memory", action="store_true", help="Opt in to model-based long-term memory")
    args = parser.parse_args()
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
        db_path = args.db if args.db is not None else (
            "data/demo.sqlite3" if args.demo else "data/conversations.sqlite3"
        )
        store = SQLiteConversationStore(db_path)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1

    try:
        memory = LongMemory(store, model) if args.long_memory else None
    except sqlite3.Error as exc:
        store.close()
        print(f"Memory startup failed: {exc}", file=sys.stderr)
        return 1
    agent = Agent(model, store, long_memory=memory)
    print("Becoming | " + ("离线模拟" if args.demo else "真实模型（发送最近对话到配置服务）"))
    print("/exit 退出 | /clear 清除当前对话历史")
    if memory is not None:
        print("长期记忆已启用：每轮回复后额外发送当前输入及有限槽位名称；相关记忆可能随回复请求发送。")
        print("/memories 查看 | /forget <key> 删除记忆及其修订（不删除原始对话）")
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
                continue
            if memory is not None and (text == "/forget" or text.startswith("/forget ")):
                key = text[len("/forget"):].strip()
                if not key:
                    print("用法：/forget <key>")
                else:
                    count = memory.forget(key)
                    print(f"已逻辑删除 {count} 条记忆修订；原始对话仍保留。")
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
