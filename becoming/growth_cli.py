"""Separate opt-in CLI; existing conversation and memory CLI remain unchanged."""
import argparse
import os
import sqlite3
import sys

from .growth_agent import GrowthAgent
from .growth_store import GrowthStore
from .memory import SQLiteConversationStore
from .models import ModelError, OpenAICompatibleModel


def main():
    parser = argparse.ArgumentParser(description="Becoming growth prototype")
    parser.add_argument("--db", default="data/growth-conversations.sqlite3")
    parser.add_argument("--growth-db", default="data/growth.sqlite3")
    parser.add_argument("--long-memory", action="store_true", help="Requires integrated memory PR")
    args = parser.parse_args()
    if (args.db != ":memory:" and args.growth_db != ":memory:"):
        from pathlib import Path
        if Path(args.db).resolve() == Path(args.growth_db).resolve():
            parser.error("Use separate transcript and growth databases")
    if args.long_memory:
        try:
            from .memory_search import ComprehensiveMemory
        except ImportError:
            parser.error("--long-memory requires integrated memory PR")
    try:
        model = OpenAICompatibleModel(os.environ.get("BECOMING_BASE_URL", "https://api.openai.com/v1"),
                                      os.environ.get("BECOMING_API_KEY", ""),
                                      os.environ.get("BECOMING_MODEL", ""))
        transcript = SQLiteConversationStore(args.db)
        try:
            growth = GrowthStore(args.growth_db)
            try:
                options = {"long_memory": ComprehensiveMemory(transcript, model)} if args.long_memory else {}
                agent = GrowthAgent(model, transcript, growth, **options)
                print("Becoming 成长实验 | 对话与查询结果将发送到配置的模型服务。")
                print("/exit 退出；/clear 清除对话（不删除成长记录）；/confirm <token> 确认；/cancel 取消")
                while True:
                    text = input("你：").strip()
                    if text == "/exit":
                        break
                    if text == "/clear":
                        agent.reply("/cancel")
                        transcript.clear()
                        print("已清除对话；成长记录仍保留。")
                        continue
                    if not text:
                        continue
                    try:
                        print("Becoming：" + agent.reply(text))
                    except (ModelError, ValueError, sqlite3.Error) as exc:
                        print("Error:", exc, file=sys.stderr)
            finally:
                growth.close()
        finally:
            transcript.close()
    except (EOFError, KeyboardInterrupt):
        print()
    except (ValueError, OSError, sqlite3.Error) as exc:
        print("Startup/storage error:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
