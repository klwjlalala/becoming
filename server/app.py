"""Development-only stateless LLM gateway. The agent lives entirely in Node."""
import json
import os
from typing import Literal
from urllib.request import Request, build_opener
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from becoming.models import NoRedirect

app = FastAPI(title="Becoming LLM gateway")
class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1,max_length=100000)
class Completion(BaseModel):
    messages: list[Message] = Field(min_length=1,max_length=40)

@app.get("/health")
def health(): return {"ok":True}

@app.post("/v1/llm/complete")
def llm(request: Completion):
    if sum(len(m.content) for m in request.messages)>500000:
        raise HTTPException(413,"Context too large")
    try:
        base=os.environ.get("BECOMING_BASE_URL",os.environ.get("BECOMING_MODEL_BASE_URL","https://api.openai.com/v1"))
        key=os.environ.get("BECOMING_API_KEY") or os.environ.get("BECOMING_MODEL_API_KEY")
        model=os.environ.get("BECOMING_MODEL")
        parsed=urlparse(base)
        if not key or not model or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (parsed.scheme=="https" or (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1","::1"))):
            raise HTTPException(503,"Model not configured")
        req=Request(base.rstrip("/")+"/chat/completions",data=json.dumps({"model":model,"messages":[m.model_dump() for m in request.messages]}).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
        with build_opener(NoRedirect()).open(req,timeout=60) as response:
            result=json.load(response)
        content=result["choices"][0]["message"]["content"]
        if not isinstance(content,str) or not content.strip() or len(content)>64000:
            raise ValueError("Invalid model response")
        return {"text":content.strip(),"usage":result.get("usage")}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,"Upstream model request failed") from None

class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1,max_length=32)

@app.post("/v1/llm/embeddings")
def embeddings(request: EmbeddingRequest):
    """Optional model forwarding for the existing embedding retrieval experiment."""
    if any(not t or len(t)>16000 for t in request.texts) or sum(map(len,request.texts))>150000:
        raise HTTPException(413,"Embedding input too large")
    try:
        base=os.environ.get("BECOMING_BASE_URL",os.environ.get("BECOMING_MODEL_BASE_URL","https://api.openai.com/v1"))
        key=os.environ.get("BECOMING_API_KEY") or os.environ.get("BECOMING_MODEL_API_KEY")
        model=os.environ.get("BECOMING_EMBEDDING_MODEL")
        parsed=urlparse(base)
        if not key or not model or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (parsed.scheme=="https" or (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1","::1"))):
            raise HTTPException(503,"Embedding model not configured")
        req=Request(base.rstrip("/")+"/embeddings",data=json.dumps({"model":model,"input":request.texts}).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
        with build_opener(NoRedirect()).open(req,timeout=60) as response:
            result=json.load(response)
        rows=result["data"]
        if not isinstance(rows,list) or len(rows)!=len(request.texts):
            raise ValueError("Invalid embedding batch")
        import math
        indexed={}
        for row in rows:
            i,v=row["index"],row["embedding"]
            if type(i) is not int or not 0<=i<len(rows) or i in indexed or not isinstance(v,list) or not 0<len(v)<=8192 or any(type(x) not in (int,float) or not math.isfinite(x) for x in v):
                raise ValueError("Invalid embedding row")
            indexed[i]=v
        return {"vectors":[indexed[i] for i in range(len(rows))],"usage":result.get("usage")}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,"Upstream embedding request failed") from None
