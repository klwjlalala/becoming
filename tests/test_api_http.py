"""Real loopback HTTP integration test for the headless API process."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


class APIHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}/api/v1"
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(ROOT),
            "BECOMING_API_HOST": "127.0.0.1",
            "BECOMING_API_PORT": str(cls.port),
            "BECOMING_API_DB": str(Path(cls.temp.name) / "conversations.sqlite3"),
            "BECOMING_API_GROWTH_DB": str(Path(cls.temp.name) / "growth.sqlite3"),
            "BECOMING_DEMO": "1",
            "BECOMING_ENABLE_LONG_MEMORY": "0",
            "BECOMING_ENABLE_PERSONAL_UNDERSTANDING": "0",
        })
        cls.process = subprocess.Popen(
            [sys.executable, "-c", "from becoming.api import run; run()"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if cls.process.poll() is not None:
                output, _ = cls.process.communicate(timeout=2)
                raise RuntimeError("API server exited before becoming healthy:\n" + output[-5000:])
            try:
                with urlopen(cls.base + "/health", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            cls.process.terminate()
            output, _ = cls.process.communicate(timeout=2)
            raise RuntimeError("API server did not become healthy:\n" + output[-5000:])

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "process", None) is not None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=5)
                if cls.process.stdout:
                    cls.process.stdout.close()
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=5)
        if getattr(cls, "temp", None) is not None:
            cls.temp.cleanup()

    def request(self, method, path, payload=None, expected=200):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = urlopen(req, timeout=5)
            status = response.status
            body = response.read()
        except HTTPError as exc:
            status = exc.code
            body = exc.read()
        self.assertEqual(status, expected, body.decode("utf-8", errors="replace"))
        return json.loads(body.decode("utf-8")) if body else None

    def test_http_lifecycle_chat_growth_and_data_clear(self):
        health = self.request("GET", "/health")
        self.assertEqual(health["status"], "ok")
        self.assertTrue(health["model_configured"])

        config = self.request("GET", "/model/config")
        self.assertTrue(config["demo"])
        self.assertIsNone(config["api_key"])

        first = self.request("POST", "/conversations", {"title": "第一个会话"}, 201)
        second = self.request("POST", "/conversations", {"title": "第二个会话"}, 201)
        first_id, second_id = first["id"], second["id"]

        sent = self.request(
            "POST", f"/conversations/{first_id}/messages",
            {"content": "你好，请介绍一下你能做什么。"},
        )
        self.assertIn("reply", sent)
        self.assertTrue(sent["message_id"])
        self.assertFalse(sent["confirmation_required"])

        first_history = self.request("GET", f"/conversations/{first_id}/messages")
        second_history = self.request("GET", f"/conversations/{second_id}/messages")
        self.assertEqual(len(first_history["items"]), 1)
        self.assertEqual(second_history["items"], [])

        preview = self.request(
            "POST", "/growth/changes",
            {"tool": "create_goal", "args": {"text": "每周自由探索一次"}},
            201,
        )
        self.assertTrue(preview["confirmation_required"])
        committed = self.request(
            "POST", f"/growth/changes/{preview['token']}/confirm"
        )
        self.assertTrue(committed["success"])
        goals = self.request("GET", "/growth/goals")
        self.assertEqual(goals["items"][0]["text"], "每周自由探索一次")
        self.request(
            "POST", f"/growth/changes/{preview['token']}/confirm", expected=409
        )

        self.assertIn("items", self.request("GET", "/memories"))
        self.assertIn("items", self.request("GET", "/understanding/claims"))
        exported = self.request("GET", "/data/export")
        self.assertEqual(len(exported["turns"]), 1)
        self.assertEqual(len(exported["growth_items"]), 1)

        clear = self.request("POST", "/data/clear")
        self.assertTrue(clear["confirmation_required"])
        result = self.request(
            "POST", "/data/clear/confirm", {"token": clear["token"]}
        )
        self.assertTrue(result["success"])
        self.assertEqual(self.request("GET", "/growth/goals")["items"], [])
        remaining = self.request("GET", "/conversations")
        self.assertEqual([item["id"] for item in remaining["items"]], ["default"])

    def test_conversation_delete_cascades_only_selected_session(self):
        first = self.request("POST", "/conversations", {"title": "保留会话"}, 201)
        second = self.request("POST", "/conversations", {"title": "删除会话"}, 201)
        self.request(
            "POST", f"/conversations/{first['id']}/messages",
            {"content": "保留的内容"},
        )
        self.request(
            "POST", f"/conversations/{second['id']}/messages",
            {"content": "将被删除的内容"},
        )
        result = self.request("DELETE", f"/conversations/{second['id']}")
        self.assertEqual(result["deleted_turns"], 1)
        self.assertEqual(
            len(self.request("GET", f"/conversations/{first['id']}/messages")["items"]),
            1,
        )
        self.request("GET", f"/conversations/{second['id']}", expected=404)


if __name__ == "__main__":
    unittest.main()
