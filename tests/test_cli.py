"""Offline command-line flow and exit behavior."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import StringIO

from becoming.__main__ import main
from becoming.models import ModelError
from becoming.growth_store import GrowthStore

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def run_cli(self, *args, stdin="", cwd=ROOT):
        env = os.environ.copy()
        for key in ("BECOMING_BASE_URL", "BECOMING_API_KEY", "BECOMING_MODEL"):
            env.pop(key, None)
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, "-m", "becoming", *args],
                              input=stdin, text=True, encoding="utf-8",
                              capture_output=True, cwd=cwd, env=env, timeout=15)

    def test_demo_exit_and_blank_input(self):
        result = self.run_cli("--demo", "--db", ":memory:", stdin="\n  \n你好\n/exit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("【模拟模型】"), 1)

    def test_eof_clean_exit(self):
        self.assertEqual(self.run_cli("--demo", "--db", ":memory:").returncode, 0)

    def test_missing_real_configuration(self):
        result = self.run_cli("--db", ":memory:")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Startup failed", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_demo_default_storage_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.run_cli("--demo", stdin="first\n/exit\n", cwd=tmp)
            second = self.run_cli("--demo", stdin="second\n/exit\n", cwd=tmp)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            path = Path(tmp) / "data" / "demo.sqlite3"
            self.assertFalse((Path(tmp) / "data" / "conversations.sqlite3").exists())
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT user_text FROM turns ORDER BY id").fetchall(),
                                 [("first",), ("second",)])

    def test_clear_then_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.sqlite3"
            result = self.run_cli("--demo", "--db", str(path),
                                  stdin="old\n/clear\nnew\n/exit\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT user_text FROM turns").fetchall(), [("new",)])

    def test_invalid_database_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("--demo", "--db", tmp)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Startup failed", result.stderr)


    def test_growth_tools_are_available_from_unified_entrypoint(self):
        result = self.run_cli("--demo", "--growth", "--db", ":memory:",
                              "--growth-db", ":memory:", stdin="你好\n/exit\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("成长辅助已启用", result.stdout)
        self.assertIn("Becoming：", result.stdout)

    def test_growth_database_requires_separate_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "same.sqlite")
            result = self.run_cli("--demo", "--growth", "--db", path,
                                  "--growth-db", path)
            self.assertEqual(result.returncode, 2)
            self.assertIn("must be separate", result.stderr)

    def test_clear_growth_requires_explicit_second_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "growth.sqlite"
            seed = GrowthStore(path)
            goal = seed.apply(seed.prepare("create_goal", {"text": "测试目标"}))["record"]
            seed.apply(seed.prepare("create_action", {"goal_id": goal["id"], "text": "测试行动"}))
            seed.close()
            with patch("sys.argv", ["becoming", "--demo", "--growth", "--db", ":memory:",
                                    "--growth-db", str(path)]), \
                 patch("builtins.input", side_effect=["/clear-growth",
                                                       "/confirm-growth-clear 12345678",
                                                       "/exit"]), \
                 patch("becoming.__main__.secrets.token_hex", return_value="12345678"), \
                 patch("sys.stdout", new_callable=StringIO) as stdout, \
                 patch("sys.stderr", new_callable=StringIO) as stderr:
                self.assertEqual(main(), 0)
                self.assertIn("成长记录已清除", stdout.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
            check = GrowthStore(path)
            try:
                self.assertEqual(check.read("list_goals", {})["items"], [])
            finally:
                check.close()

    def test_clear_conversation_does_not_delete_growth_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "growth.sqlite"
            seed = GrowthStore(path)
            seed.apply(seed.prepare("create_goal", {"text": "保留的目标"}))
            seed.close()
            result = self.run_cli("--demo", "--growth", "--db", ":memory:",
                                  "--growth-db", str(path), stdin="/clear\n/exit\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            check = GrowthStore(path)
            try:
                self.assertEqual(check.read("list_goals", {})["items"][0]["text"], "保留的目标")
            finally:
                check.close()

    def test_cli_continues_after_model_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "retry.sqlite3"
            with patch("sys.argv", ["becoming", "--demo", "--db", str(path)]), \
                 patch("builtins.input", side_effect=["failed", "success", "/exit"]), \
                 patch("becoming.models.DemoModel.complete", side_effect=[ModelError("offline error"), "ok"]), \
                 patch("sys.stdout", new_callable=StringIO) as stdout, \
                 patch("sys.stderr", new_callable=StringIO) as stderr:
                self.assertEqual(main(), 0)
                self.assertIn("ok", stdout.getvalue())
                self.assertIn("offline error", stderr.getvalue())
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT user_text FROM turns").fetchall(), [("success",)])


if __name__ == "__main__":
    unittest.main()
