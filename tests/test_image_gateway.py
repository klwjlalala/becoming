import base64
import json
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from server.app import ImageGenerationRequest, generate_image


PNG = base64.b64encode(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"test-png-data").decode()


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def open(self, request, timeout):
        self.request = request
        if timeout != 180:
            raise AssertionError("Image provider timeout should be bounded")
        return FakeResponse(self.payload)


class ImageGatewayTests(unittest.TestCase):
    def test_unconfigured_image_provider_returns_503(self):
        env = os.environ.copy()
        env.pop("BECOMING_IMAGE_MODEL", None)
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(HTTPException) as caught:
                generate_image(ImageGenerationRequest(prompt="A quiet landscape"))
        self.assertEqual(caught.exception.status_code, 503)

    def test_image_gateway_returns_validated_png_bytes(self):
        opener = FakeOpener({"data": [{"b64_json": PNG, "revised_prompt": "A quiet landscape"}]})
        env = {
            "BECOMING_IMAGE_MODEL": "test-image-model",
            "BECOMING_IMAGE_BASE_URL": "https://images.example/v1",
            "BECOMING_IMAGE_API_KEY": "test-image-key",
        }
        with patch.dict(os.environ, env, clear=False), patch("server.app.build_opener", return_value=opener):
            result = generate_image(ImageGenerationRequest(prompt="A quiet landscape", size="1024x1024"))
        self.assertEqual(result["mime_type"], "image/png")
        self.assertEqual(base64.b64decode(result["image_base64"]), base64.b64decode(PNG))
        self.assertEqual(result["revised_prompt"], "A quiet landscape")
        self.assertEqual(opener.request.full_url, "https://images.example/v1/images/generations")

    def test_image_gateway_rejects_non_image_provider_payload(self):
        opener = FakeOpener({"data": [{"b64_json": base64.b64encode(b"<svg></svg>").decode()}]})
        env = {
            "BECOMING_IMAGE_MODEL": "test-image-model",
            "BECOMING_IMAGE_BASE_URL": "https://images.example/v1",
            "BECOMING_IMAGE_API_KEY": "test-image-key",
        }
        with patch.dict(os.environ, env, clear=False), patch("server.app.build_opener", return_value=opener):
            with self.assertRaises(HTTPException) as caught:
                generate_image(ImageGenerationRequest(prompt="A quiet landscape"))
        self.assertEqual(caught.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
