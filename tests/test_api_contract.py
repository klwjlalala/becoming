"""Public V1 route compatibility check against the real app's OpenAPI schema."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class APIContractTests(unittest.TestCase):
    def test_v1_routes_and_required_inputs_remain_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("BECOMING_")}
            env.update({
                "BECOMING_DEMO": "1",
                "BECOMING_API_DB": str(Path(directory) / "conversation.sqlite3"),
                "BECOMING_API_GROWTH_DB": str(Path(directory) / "growth.sqlite3"),
            })
            result = subprocess.run(
                [sys.executable, "-c",
                 "import json; from becoming.api import app; print(json.dumps(app.openapi())); app.state.runtime.close()"],
                cwd=ROOT, env=env, capture_output=True, text=True, check=True, timeout=20,
            )
            schema = json.loads(result.stdout)
        expected = json.loads((ROOT / "docs/api-v1-routes.json").read_text(encoding="utf-8"))
        for item in expected:
            with self.subTest(route=item):
                self.assertIn(item["method"].lower(), schema["paths"].get(item["path"], {}))
        schemas = schema["components"]["schemas"]
        for name, required in {
            "MessageInput": {"content"},
            "ModelConfigInput": {"base_url", "api_key", "model"},
            "ConfirmationInput": {"token"},
            "GrowthChangeInput": {"tool", "args"},
        }.items():
            self.assertEqual(set(schemas[name]["required"]), required)
