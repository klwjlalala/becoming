"""Development gateway: fixed account, provider proxy, usage ledger and append-only turn sync."""
import hmac
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal
from urllib.request import Request, build_opener
from urllib.parse import urlparse
from uuid import UUID
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from becoming.models import NoRedirect

app = FastAPI(title="Becoming gateway")
def db():
    path = Path(os.environ.get("BECOMING_SERVER_DB", "data/server.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript("""
      CREATE TABLE IF NOT EXISTS usage(account TEXT, request_id TEXT, status TEXT NOT NULL,
        input_tokens INTEGER, output_tokens INTEGER, cost_microunits INTEGER, PRIMARY KEY(account,request_id));
      CREATE TABLE IF NOT EXISTS turns(seq INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL,
        id TEXT NOT NULL, user TEXT NOT NULL, assistant TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(account,id));
      CREATE INDEX IF NOT EXISTS turns_account_seq ON turns(account,seq);
    """)
    return con

@contextmanager
def transaction():
    with closing(db()) as con:
        with con:
            yield con

def account(authorization: str = Header(default=""), x_becoming_account: str | None = Header(default=None)):
    token = os.environ.get("BECOMING_TOKEN", "")
    if not token or not hmac.compare_digest(authorization.encode(), ("Bearer "+token).encode()):
        raise HTTPException(401, "Unauthorized")
    user = os.environ.get("BECOMING_ACCOUNT", "dev")
    if x_becoming_account is not None and x_becoming_account != user:
        raise HTTPException(403, "Account namespace mismatch")
    return user

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1,max_length=100000)
class Completion(BaseModel):
    request_id: UUID
    messages: list[Message] = Field(min_length=1,max_length=30)

def complete(messages):
    if os.environ.get("BECOMING_DEMO") == "1":
        return "【模拟模型】对话链路已连接。真实模型需在服务端配置。", 0, 0, True
    base = os.environ.get("BECOMING_MODEL_BASE_URL","")
    parsed = urlparse(base)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (parsed.scheme=="https" or (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1","::1"))):
        raise ValueError("Invalid provider URL")
    key, model = os.environ["BECOMING_MODEL_API_KEY"], os.environ["BECOMING_MODEL"]
    request = Request(base.rstrip("/")+"/chat/completions",
        data=json.dumps({"model":model,"messages":[m.model_dump() for m in messages]}).encode(),
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
    with build_opener(NoRedirect()).open(request,timeout=60) as response:
        payload=json.load(response)
    text=payload["choices"][0]["message"]["content"]
    if not isinstance(text,str) or not text.strip() or len(text)>64000:
        raise ValueError("Invalid model text")
    usage=payload.get("usage") or {}
    def count(key):
        value=usage.get(key)
        return value if type(value) is int and 0<=value<=10**9 else None
    return text.strip(),count("prompt_tokens"),count("completion_tokens"),False

@app.get("/health")
def health(): return {"ok":True}

@app.post("/v1/llm/complete")
def llm(request: Completion, user=Depends(account)):
    if sum(len(m.content) for m in request.messages)>500000:
        raise HTTPException(413,"Context too large")
    rid=str(request.request_id)
    try:
        with transaction() as con:
            con.execute("INSERT INTO usage(account,request_id,status) VALUES(?,?,?)",(user,rid,"pending"))
    except sqlite3.IntegrityError:
        raise HTTPException(409,"Request already recorded; do not replay automatically")
    try:
        text,inp,out,demo=complete(request.messages)
        rates=[os.environ.get("BECOMING_INPUT_MICRO_PER_MILLION"),os.environ.get("BECOMING_OUTPUT_MICRO_PER_MILLION")]
        cost=0 if demo else None
        if not demo and inp is not None and out is not None and all(r is not None for r in rates):
            a,b=map(int,rates)
            if min(a,b)<0 or max(a,b)>10**9: raise ValueError("Invalid rates")
            cost=(inp*a+out*b+999999)//1000000
        with transaction() as con:
            con.execute("UPDATE usage SET status=?,input_tokens=?,output_tokens=?,cost_microunits=? WHERE account=? AND request_id=?",
                        ("demo" if demo else "completed",inp,out,cost,user,rid))
        return {"text":text,"usage":{"input_tokens":inp,"output_tokens":out,"cost_microunits":cost}}
    except Exception:
        with transaction() as con:
            con.execute("UPDATE usage SET status='uncertain' WHERE account=? AND request_id=?",(user,rid))
        raise HTTPException(502,"Model request or usage recording failed") from None

@app.get("/v1/usage")
def usage(user=Depends(account)):
    with transaction() as con:
        return {"records":[dict(r) for r in con.execute("SELECT request_id,status,input_tokens,output_tokens,cost_microunits FROM usage WHERE account=? ORDER BY rowid DESC LIMIT 100",(user,))]}

class Turn(BaseModel):
    id: UUID
    user: str = Field(min_length=1,max_length=16000)
    assistant: str = Field(min_length=1,max_length=64000)
    created_at: str = Field(min_length=1,max_length=40)
    @field_validator("created_at")
    @classmethod
    def date(cls,v):
        if datetime.fromisoformat(v.replace("Z","+00:00")).tzinfo is None: raise ValueError("Timezone required")
        return v
class Sync(BaseModel):
    cursor: int = Field(ge=0,le=2**53-1)
    turns: list[Turn] = Field(max_length=100)

@app.post("/v1/sync/turns")
def sync(request: Sync,user=Depends(account)):
    with transaction() as con:
        con.execute("BEGIN IMMEDIATE")
        latest=con.execute("SELECT COALESCE(MAX(seq),0) FROM turns WHERE account=?",(user,)).fetchone()[0]
        if request.cursor>latest: raise HTTPException(409,"Invalid cursor")
        ack=[]
        for t in request.turns:
            ident=str(t.id)
            previous=con.execute("SELECT user,assistant,created_at FROM turns WHERE account=? AND id=?",(user,ident)).fetchone()
            values=(t.user,t.assistant,t.created_at)
            if previous and tuple(previous)!=values: raise HTTPException(409,"Turn identity conflict")
            if not previous:
                con.execute("INSERT INTO turns(account,id,user,assistant,created_at) VALUES(?,?,?,?,?)",(user,ident,*values))
            ack.append(ident)
        rows=con.execute("SELECT seq,id,user,assistant,created_at FROM turns WHERE account=? AND seq>? ORDER BY seq LIMIT 100",(user,request.cursor)).fetchall()
        return {"ack":ack,"turns":[{k:r[k] for k in ("id","user","assistant","created_at")} for r in rows],"cursor":rows[-1]["seq"] if rows else request.cursor}
