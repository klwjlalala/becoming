"""HTTP smoke test across actual Python gateway, Node runtime and browser endpoints."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parents[1]

def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        return sock.getsockname()[1]

def get(url, data=None, headers=None):
    h = dict(headers or {})
    if data is not None: h["Content-Type"]="application/json"
    with urlopen(Request(url, data=None if data is None else json.dumps(data).encode(),headers=h),timeout=10) as response:
        return response.read()

def wait(fn):
    last=None
    for _ in range(100):
        try:
            result=fn()
            if result: return result
        except (OSError,ValueError) as e: last=e
        time.sleep(.2)
    raise AssertionError(f"Service or state not ready: {last}")

def stop(p):
    if p.poll() is None:
        p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()

def main():
    with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
        gateway_port, local_port = port(), port()
        while local_port == gateway_port: local_port=port()
        gateway=f"http://127.0.0.1:{gateway_port}"
        local=f"http://127.0.0.1:{local_port}"
        token="smoke-test-token"
        env={**os.environ,"BECOMING_TOKEN":token,"BECOMING_ACCOUNT":"smoke","BECOMING_DEMO":"1","BECOMING_SYNC":"1",
            "BECOMING_SERVER_DB":temp+"/cloud.db","BECOMING_LOCAL_DB":temp+"/local.db","BECOMING_GATEWAY":gateway,"BECOMING_LOCAL_PORT":str(local_port)}
        def launch(args):
            p=subprocess.Popen(args,cwd=ROOT,env=env)
            stack.callback(stop,p)
            return p
        launch([sys.executable,"-m","uvicorn","server.app:app","--host","127.0.0.1","--port",str(gateway_port)])
        wait(lambda:get(gateway+"/health"))
        runtime=launch(["node","agent-runtime/server.mjs"])
        wait(lambda:get(local+"/api/status"))
        assert b"Agent Lab" in get(local+"/")
        turn=json.loads(get(local+"/api/chat",{"text":"fictional test message"},{"Origin":local}))["turn"]
        assert "模拟模型" in turn["assistant"]
        assert json.loads(get(local+"/api/history"))["turns"][0]["id"]==turn["id"]
        wait(lambda:json.loads(get(local+"/api/status"))["pending"]==0)
        auth={"Authorization":"Bearer "+token,"X-Becoming-Account":"smoke"}
        synced=json.loads(get(gateway+"/v1/sync/turns",{"cursor":0,"turns":[]},auth))
        assert [t["id"] for t in synced["turns"]]==[turn["id"]]
        usage=json.loads(get(gateway+"/v1/usage",headers=auth))["records"]
        assert len(usage)==1 and usage[0]["status"]=="demo"
        stop(runtime)
        launch(["node","agent-runtime/server.mjs"])
        wait(lambda:get(local+"/api/status"))
        assert json.loads(get(local+"/api/history"))["turns"][0]["id"]==turn["id"]
        print("Gateway / local runtime / browser / sync / restart: OK")

if __name__=="__main__":
    main()
