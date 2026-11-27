"""Run actual HTTP gateway and Node runtime against a local fake provider."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request,urlopen
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
class Provider(BaseHTTPRequestHandler):
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system=payload["messages"][0]["content"]
        text="测试回复"
        if "你是记忆提取器" in system:
            user=json.loads(payload["messages"][1]["content"])["current_user_message"]
            text=json.dumps([{"key":"职业","category":"fact","quote":user,"replaces":None}],ensure_ascii=False)
        if "你是个人理解更新引擎" in system:
            text=json.dumps({"evidence":[],"operations":[],"confirmation":None})
        body=json.dumps({"choices":[{"message":{"content":text}}]}).encode()
        self.send_response(200);self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(body)
def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0));return s.getsockname()[1]
def get(url,data=None,headers=None):
    h=dict(headers or {})
    if data is not None:h["Content-Type"]="application/json"
    with urlopen(Request(url,data=None if data is None else json.dumps(data).encode(),headers=h),timeout=10) as r:return r.read()
def wait(fn):
    for _ in range(100):
        try:
            if result:=fn():return result
        except (OSError,ValueError):pass
        time.sleep(.2)
    raise AssertionError("Service/state not ready")
def stop(p):
    if p.poll() is None:
        p.terminate()
        try:p.wait(timeout=5)
        except subprocess.TimeoutExpired:p.kill();p.wait()
def main():
    with tempfile.TemporaryDirectory() as temp,ExitStack() as stack:
        provider=ThreadingHTTPServer(("127.0.0.1",0),Provider)
        threading.Thread(target=provider.serve_forever,daemon=True).start()
        stack.callback(provider.server_close);stack.callback(provider.shutdown)
        gp,lp=port(),port()
        while lp==gp:lp=port()
        gateway=f"http://127.0.0.1:{gp}";local=f"http://127.0.0.1:{lp}"
        env={**os.environ,"BECOMING_BASE_URL":f"http://127.0.0.1:{provider.server_port}/v1","BECOMING_API_KEY":"fake","BECOMING_MODEL":"fake","BECOMING_LOCAL_DB":temp+"/agent.db","BECOMING_GATEWAY":gateway,"BECOMING_LOCAL_PORT":str(lp),"BECOMING_ENABLE_LONG_MEMORY":"1"}
        def launch(args):
            p=subprocess.Popen(args,cwd=ROOT,env=env);stack.callback(stop,p);return p
        launch([sys.executable,"-m","uvicorn","server.app:app","--host","127.0.0.1","--port",str(gp)])
        wait(lambda:get(gateway+"/health"))
        runtime=launch(["node","agent-runtime/server.mjs"]);wait(lambda:get(local+"/api/status"))
        assert b"Agent Lab" in get(local+"/")
        turn=json.loads(get(local+"/api/chat",{"text":"我的职业是教师"},{"Origin":local}))["turn"]
        assert turn["assistant"]=="测试回复"
        wait(lambda:json.loads(get(local+"/api/memories"))["memories"])
        assert json.loads(get(local+"/api/memories"))["memories"][0]["quote"]=="我的职业是教师"
        stop(runtime);launch(["node","agent-runtime/server.mjs"]);wait(lambda:get(local+"/api/status"))
        assert json.loads(get(local+"/api/history"))["turns"][0]["id"]==turn["id"]
        assert len(json.loads(get(local+"/api/memories"))["memories"])==1
        print("Gateway / runtime / memory / browser / restart: OK")
if __name__=="__main__":main()
