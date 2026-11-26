import io
import json
import unittest
from unittest.mock import patch
from becoming.models import OpenAICompatibleModel, ModelError


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.model = OpenAICompatibleModel("https://example.test/v1", "fake", "test-model")

    @patch("becoming.models.urlopen")
    def test_request_and_response(self, request):
        request.return_value = io.BytesIO(b'{"choices":[{"message":{"content":"hello"}}]}')
        self.assertEqual(self.model.complete([{"role": "user", "content": "hi"}]), "hello")
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(json.loads(sent.data)["model"], "test-model")

    @patch("becoming.models.urlopen")
    def test_invalid_response(self, request):
        request.return_value = io.BytesIO(b'{"choices":[]}')
        with self.assertRaises(ModelError):
            self.model.complete([])

    def test_insecure_remote_url(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleModel("http://example.test/v1", "fake", "model")


if __name__ == "__main__":
    unittest.main()
