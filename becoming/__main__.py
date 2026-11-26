"""CLI for offline smoke tests and optional real model conversations."""
import argparse
import os
import sqlite3
import sys

from .agent import Agent
from .memory import SQLiteConversationStore
from .models import DemoModel, OpenAICompatibleModel, ModelError


def main() -> int:
    parser = argparse.ArgumentParser(description="Becoming AI companion prototype")
    parser.add_argument("--demo", action="store_true", help="Offline mock model")
    parser.add_argument("--db", default=None, help="SQLite file or :memory:")
    args = parser.parse_args()
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

    agent = Agent(model, store)
    print("Becoming | " + ("离线模拟" if args.demo else "真实模型（发送最近对话到配置服务）"))
    print("/exit 退出 | /clear 清除当前对话历史")
    try:
        while True:
            text = input("你：").strip()
            if text == "/exit":
                break
            if text == "/clear":
                store.clear()
                print("对话历史已清除。")
                continue
            if not text:
                continue
            try:
                print("Becoming：" + agent.reply(text))
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
