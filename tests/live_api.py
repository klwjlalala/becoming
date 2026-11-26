"""Manual real-model HTTP smoke test. Uses only synthetic test data."""
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
REQUIRED = ("BECOMING_BASE_URL", "BECOMING_API_KEY", "BECOMING_MODEL")


@unittest.skipUnless(all(os.environ.get(key) for key in REQUIRED),
                     "Real model credentials are not configured")
class LiveAPIHTTPTests(unittest.TestCase):
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
            "BECOMING_ENABLE_LONG_MEMORY": "1",
            "BECOMING_ENABLE_PERSONAL_UNDERSTANDING": "1",
        })
        cls.process = subprocess.Popen(
            [sys.executable, "-c", "from becoming.api import run; run()"],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            if cls.process.poll() is not None:
                raise RuntimeError("API service exited during live smoke-test startup")
            try:
                with urlopen(cls.base + "/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        else:
            cls.process.terminate()
            cls.process.wait(timeout=5)
            raise RuntimeError("API service did not become healthy")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "process", None) is not None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=5)
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
            response = urlopen(req, timeout=90)
            status, body = response.status, response.read()
        except HTTPError as exc:
            status, body = exc.code, exc.read()
        self.assertEqual(status, expected, body.decode("utf-8", errors="replace"))
        return json.loads(body.decode("utf-8")) if body else None

    def test_real_model_through_http_and_growth_state(self):
        health = self.request("GET", "/health")
        self.assertEqual(health["status"], "ok")
        self.assertTrue(health["model_configured"])

        tested = self.request("POST", "/model/test", {
            "base_url": os.environ["BECOMING_BASE_URL"],
            "api_key": os.environ["BECOMING_API_KEY"],
            "model": os.environ["BECOMING_MODEL"],
        })
        self.assertTrue(tested["success"])

        conversation = self.request(
            "POST", "/conversations", {"title": "真实模型 API 联调"}, 201
        )
        result = self.request(
            "POST", f"/conversations/{conversation['id']}/messages",
            {"content": "我长期偏好在晚上阅读纸质小说。这是一条用于接口联调的合成测试数据。"},
        )
        self.assertIsInstance(result["reply"], str)
        self.assertTrue(result["reply"].strip())
        self.assertTrue(result["message_id"])

        history = self.request(
            "GET", f"/conversations/{conversation['id']}/messages"
        )
        self.assertEqual(len(history["items"]), 1)

        # Verify both real-model post-turn processors finish outside the
        # chat request, not merely that the HTTP stub accepts their payloads.
        deadline = time.time() + 180
        while time.time() < deadline:
            jobs = self.request(
                "GET", f"/background/jobs?source_turn_id={result['message_id']}&limit=10"
            )["items"]
            if len(jobs) == 2 and all(job["status"] == "done" for job in jobs):
                break
            if any(job["status"] == "failed" for job in jobs):
                self.fail(f"Real-model background processing failed: {jobs}")
            time.sleep(0.5)
        else:
            self.fail(f"Real-model background processing timed out: {jobs}")
        self.assertEqual(
            {job["kind"] for job in jobs},
            {"long_memory.extract", "personal_understanding.process"},
        )

        preview = self.request(
            "POST", "/growth/changes",
            {"tool": "create_goal", "args": {"text": "API 联调临时目标"}},
            201,
        )
        committed = self.request(
            "POST", f"/growth/changes/{preview['token']}/confirm"
        )
        self.assertTrue(committed["success"])
        self.assertEqual(
            self.request("GET", "/growth/goals")["items"][0]["text"],
            "API 联调临时目标",
        )

        clear = self.request("POST", "/data/clear")
        self.request("POST", "/data/clear/confirm", {"token": clear["token"]})


if __name__ == "__main__":
    unittest.main()
