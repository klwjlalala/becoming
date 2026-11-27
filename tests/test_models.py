import io
import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request
from unittest.mock import patch
from becoming.models import OpenAICompatibleModel, ModelError, NoRedirect


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.model = OpenAICompatibleModel("https://example.test/v1", "fake", "test-model")

    @patch("becoming.models.build_opener")
    def test_request_and_response(self, request):
        request.return_value.open.return_value = io.BytesIO(b'{"choices":[{"message":{"content":"hello"}}]}')
        self.assertEqual(self.model.complete([{"role": "user", "content": "hi"}]), "hello")
        sent = request.return_value.open.call_args.args[0]
        self.assertEqual(sent.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(json.loads(sent.data)["model"], "test-model")

    @patch("becoming.models.build_opener")
    def test_invalid_response(self, request):
        request.return_value.open.return_value = io.BytesIO(b'{"choices":[]}')
        with self.assertRaises(ModelError):
            self.model.complete([])

    def test_redirect_never_forwards_credentials(self):
        request = Request("https://example.test/v1/chat/completions",
                          headers={"Authorization": "Bearer fake"}, data=b"private")
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code), self.assertRaises(HTTPError):
                NoRedirect().redirect_request(request, None, code, "", {},
                                             "https://other.test/receive")

    def test_insecure_remote_url(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleModel("http://example.test/v1", "fake", "model")


if __name__ == "__main__":
    unittest.main()
