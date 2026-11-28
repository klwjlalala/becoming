import json
import os
import unittest
from unittest.mock import patch,MagicMock
from fastapi.testclient import TestClient
from server.app import app

class GatewayTest(unittest.TestCase):
    @patch.dict(os.environ,{"BECOMING_BASE_URL":"http://127.0.0.1:9999/v1","BECOMING_API_KEY":"test-only","BECOMING_MODEL":"test-model"})
    @patch("server.app.build_opener")
    def test_forward(self,opener):
        response=MagicMock()
        response.read.return_value=json.dumps({"choices":[{"message":{"content":"hello"}}],"usage":{"prompt_tokens":1}}).encode()
        opener.return_value.open.return_value.__enter__.return_value=response
        with TestClient(app) as client:
            result=client.post("/v1/llm/complete",json={"messages":[{"role":"user","content":"hi"}]})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json(),{"text":"hello","usage":{"prompt_tokens":1}})
        req=opener.return_value.open.call_args.args[0]
        self.assertEqual(req.full_url,"http://127.0.0.1:9999/v1/chat/completions")
        self.assertEqual(json.loads(req.data),{"model":"test-model","messages":[{"role":"user","content":"hi"}]})
    @patch.dict(os.environ,{"BECOMING_BASE_URL":"http://example.org/v1","BECOMING_API_KEY":"test","BECOMING_MODEL":"m"})
    def test_insecure_provider_refused(self):
        with TestClient(app) as client:
            self.assertEqual(client.post("/v1/llm/complete",json={"messages":[{"role":"user","content":"hi"}]}).status_code,503)

    @patch.dict(os.environ,{"BECOMING_BASE_URL":"http://127.0.0.1:9999/v1","BECOMING_API_KEY":"test-only","BECOMING_MODEL":"test-model"})
    @patch("server.app.build_opener")
    def test_stream_forward(self,opener):
        response=MagicMock()
        response.read.side_effect=[b'data: {"choices":[{"delta":{"content":"hello"}}]}\\n\\n',b'data: [DONE]\\n\\n',b'']
        opener.return_value.open.return_value=response
        with TestClient(app) as client:
            result=client.post("/v1/llm/stream",json={"messages":[{"role":"user","content":"hi"}]})
        self.assertEqual(result.status_code,200)
        self.assertIn('"content":"hello"',result.text)
        req=opener.return_value.open.call_args.args[0]
        self.assertEqual(json.loads(req.data),{"model":"test-model","messages":[{"role":"user","content":"hi"}],"stream":True})
        response.close.assert_called_once()
