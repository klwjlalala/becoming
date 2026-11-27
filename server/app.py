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
