"""Real loopback HTTP integration test for the headless API process."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


class FakeModelHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size).decode("utf-8"))
        messages = payload.get("messages", [])
        user_text = next(
            (item.get("content", "") for item in reversed(messages)
             if item.get("role") == "user"),
            "",
        )
        system_text = messages[0].get("content", "") if messages else ""
        if "你是记忆提取器" in system_text:
            try:
                extraction_input = json.loads(messages[-1].get("content", "{}"))
                current = extraction_input.get("current_user_message", "")
            except (ValueError, AttributeError):
                current = ""
            if current == "我喜欢晚上阅读。":
                reply = json.dumps([{
                    "key": "reading_time",
                    "category": "subjective",
                    "quote": "我喜欢晚上阅读。",
                    "replaces": None,
                }], ensure_ascii=False)
            else:
                reply = "[]"
        elif "你是个人理解更新引擎" in system_text:
            update_input = json.loads(messages[-1].get("content", "{}"))
            target = next(
                (turn for turn in update_input.get("turns", [])
                 if "我更在意能自己安排时间。" in turn.get("user_text", "")),
                None,
            )
            if target is None:
                reply = json.dumps({
                    "evidence": [], "operations": [], "confirmation": None,
                }, ensure_ascii=False)
            else:
                reply = json.dumps({
                    "evidence": [{
                        "ref": "e1",
                        "turn_index": target["turn_index"],
                        "quote": "我更在意能自己安排时间。",
                        "kind": "direct_statement",
                        "event_time": None,
                    }],
                    "operations": [{
                        "operation": "CREATE",
                        "claim_ref": "c1",
                        "claim_id": None,
                        "expected_version": None,
                        "content": "用户重视自主安排时间。",
                        "dimension": "values",
                        "basis": "explicit_statement",
                        "scope": {},
                        "temporal_scope": "ongoing",
                        "evidence": [{"ref": "e1", "relation": "support"}],
                        "reason": "用户直接表达了对自主时间的偏好。",
                    }],
                    "confirmation": None,
                }, ensure_ascii=False)
        elif "请帮我创建成长目标" in user_text:
            reply = (
                "GROWTH_TOOL\n"
                + json.dumps({
                    "tool": "create_goal",
                    "args": {"text": "每周自由探索一次"},
                }, ensure_ascii=False)
            )
        elif "你还记得我喜欢什么时候阅读吗" in user_text:
            reply = "你之前提到喜欢晚上阅读。"
        elif "Connection test" in user_text:
            reply = "OK"
        else:
            reply = "模拟模型回复。"
        body = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": reply}}]
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class APIHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.model_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
        cls.model_port = cls.model_server.server_address[1]
        cls.model_thread = threading.Thread(target=cls.model_server.serve_forever, daemon=True)
        cls.model_thread.start()

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}/api/v1"
        env = os.environ.copy()
        env.pop("BECOMING_DEMO", None)
        env.update({
            "PYTHONPATH": str(ROOT),
            "BECOMING_API_HOST": "127.0.0.1",
            "BECOMING_API_PORT": str(cls.port),
            "BECOMING_API_DB": str(Path(cls.temp.name) / "conversations.sqlite3"),
            "BECOMING_API_GROWTH_DB": str(Path(cls.temp.name) / "growth.sqlite3"),
            "BECOMING_BASE_URL": f"http://127.0.0.1:{cls.model_port}/v1",
            "BECOMING_API_KEY": "test-api-key-never-return-this",
            "BECOMING_MODEL": "test-model",
            "BECOMING_ENABLE_LONG_MEMORY": "1",
            "BECOMING_ENABLE_PERSONAL_UNDERSTANDING": "1",
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
        if getattr(cls, "model_server", None) is not None:
            cls.model_server.shutdown()
            cls.model_server.server_close()
        if getattr(cls, "temp", None) is not None:
            cls.temp.cleanup()

    def setUp(self):
        pending = self.request("POST", "/data/clear")
        self.request("POST", "/data/clear/confirm", {"token": pending["token"]})

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
        self.assertFalse(config["demo"])
        self.assertTrue(config["api_key_configured"])
        self.assertIsNone(config["api_key"])

        model_test = self.request("POST", "/model/test", {
            "base_url": f"http://127.0.0.1:{self.model_port}/v1",
            "api_key": "temporary-test-key",
            "model": "test-model",
        })
        self.assertTrue(model_test["success"])

        first = self.request("POST", "/conversations", {"title": "第一个会话"}, 201)
        second = self.request("POST", "/conversations", {"title": "第二个会话"}, 201)
        first_id, second_id = first["id"], second["id"]

        sent = self.request(
            "POST", f"/conversations/{first_id}/messages",
            {"content": "你好，请介绍一下你能做什么。"},
        )
        self.assertIn("模拟模型回复", sent["reply"])
        self.assertTrue(sent["message_id"])
        self.assertFalse(sent["confirmation_required"])

        self.request(
            "POST", f"/conversations/{first_id}/messages",
            {"content": "我喜欢晚上阅读。"},
        )
        saved_memories = self.request("GET", "/memories")
        self.assertEqual(saved_memories["items"][0]["quote"], "我喜欢晚上阅读。")

        recall = self.request(
            "POST", f"/conversations/{second_id}/messages",
            {"content": "你还记得我喜欢什么时候阅读吗？"},
        )
        self.assertIn("晚上阅读", recall["reply"])

        proposal = self.request(
            "POST", f"/conversations/{first_id}/messages",
            {"content": "请帮我创建成长目标：每周自由探索一次。"},
        )
        self.assertTrue(proposal["confirmation_required"])
        self.assertEqual(proposal["growth_event"]["status"], "proposed")
        token = proposal["confirmation"]["token"]
        self.assertNotIn(token, proposal["reply"])
        committed = self.request(
            "POST", f"/conversations/{first_id}/confirm", {"token": token}
        )
        self.assertEqual(committed["growth_event"]["status"], "committed")

        first_history = self.request("GET", f"/conversations/{first_id}/messages")
        second_history = self.request("GET", f"/conversations/{second_id}/messages")
        self.assertEqual(len(first_history["items"]), 5)
        self.assertEqual(len(second_history["items"]), 2)

        goals = self.request("GET", "/growth/goals")
        self.assertEqual(goals["items"][0]["text"], "每周自由探索一次")
        deleted = self.request("DELETE", "/memories/reading_time")
        self.assertEqual(deleted["deleted_versions"], 1)
        self.assertEqual(self.request("GET", "/memories")["items"], [])
        allowed = self.request("POST", "/memories/reading_time/allow")
        self.assertTrue(allowed["allowed"])
        self.request(
            "POST", f"/conversations/{second_id}/messages",
            {"content": "我喜欢晚上阅读。"},
        )
        self.assertEqual(len(self.request("GET", "/memories")["items"]), 1)

        understanding = self.request(
            "POST", f"/conversations/{first_id}/messages",
            {"content": "我想更新你对我的理解：我更在意能自己安排时间。"},
        )
        self.assertEqual(
            len(understanding["understanding_event"]["written_claim_ids"]), 1
        )
        claims = self.request("GET", "/understanding/claims")
        self.assertEqual(len(claims["items"]), 1)
        claim_id = claims["items"][0]["id"]
        detail = self.request("GET", f"/understanding/claims/{claim_id}")
        self.assertEqual(detail["claim"]["content"], "用户重视自主安排时间。")
        self.assertEqual(len(detail["history"]), 1)

        self.assertIn("items", self.request("GET", "/understanding/claims"))
        exported = self.request("GET", "/data/export")
        self.assertEqual(len(exported["turns"]), 7)
        self.assertEqual(len(exported["long_memories"]), 1)
        self.assertEqual(len(exported["personal_understanding"]), 1)
        self.assertEqual(len(exported["growth_items"]), 1)

        self.request("DELETE", f"/conversations/{first_id}")
        self.assertEqual(self.request("GET", "/understanding/claims")["items"], [])
        self.assertEqual(len(self.request("GET", "/memories")["items"]), 1)

        clear = self.request("POST", "/data/clear")
        self.assertTrue(clear["confirmation_required"])
        result = self.request(
            "POST", "/data/clear/confirm", {"token": clear["token"]}
        )
        self.assertTrue(result["success"])
        self.assertEqual(self.request("GET", "/growth/goals")["items"], [])
        self.assertEqual(self.request("GET", "/memories")["items"], [])
        remaining = self.request("GET", "/conversations")
        self.assertEqual([item["id"] for item in remaining["items"]], ["default"])

        secret = "do-not-return-this-key"
        updated = self.request("PUT", "/model/config", {
            "base_url": f"http://127.0.0.1:{self.model_port}/v1",
            "api_key": secret,
            "model": "test-model",
        })
        self.assertIsNone(updated["api_key"])
        self.assertNotIn(secret, json.dumps(updated))
        self.assertNotIn(secret, json.dumps(self.request("GET", "/model/config")))

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
