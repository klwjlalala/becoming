import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from server.app import app

class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"BECOMING_SERVER_DB":self.temp.name+"/server.db","BECOMING_TOKEN":"test-token","BECOMING_ACCOUNT":"test","BECOMING_DEMO":"1"})
        self.env.start()
        self.client=TestClient(app)
        self.auth={"Authorization":"Bearer test-token"}
    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.temp.cleanup()
    def test_auth_and_usage(self):
        data={"request_id":str(uuid4()),"messages":[{"role":"user","content":"hello"}]}
        self.assertEqual(self.client.post("/v1/llm/complete",json=data).status_code,401)
        self.assertEqual(self.client.post("/v1/llm/complete",json=data,headers=self.auth).status_code,200)
        self.assertEqual(self.client.post("/v1/llm/complete",json=data,headers=self.auth).status_code,409)
        records=self.client.get("/v1/usage",headers=self.auth).json()["records"]
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]["cost_microunits"],0)
    def test_sync_idempotency_and_isolation(self):
        turn={"id":str(uuid4()),"user":"a","assistant":"b","created_at":"2026-01-01T00:00:00Z"}
        data={"cursor":0,"turns":[turn]}
        first=self.client.post("/v1/sync/turns",json=data,headers=self.auth).json()
        second=self.client.post("/v1/sync/turns",json=data,headers=self.auth).json()
        self.assertEqual(first,second)
        self.assertEqual(len(first["turns"]),1)
        bad={"cursor":0,"turns":[{**turn,"user":"changed"}]}
        self.assertEqual(self.client.post("/v1/sync/turns",json=bad,headers=self.auth).status_code,409)
        with patch.dict(os.environ,{"BECOMING_ACCOUNT":"other"}):
            self.assertEqual(self.client.post("/v1/sync/turns",json={"cursor":0,"turns":[]},headers=self.auth).json()["turns"],[])
