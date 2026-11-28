"""Development-only stateless LLM gateway. The agent lives entirely in Node."""
import json
import base64
import os
import re
from typing import Literal
from urllib.request import Request, build_opener
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from becoming.models import NoRedirect

app = FastAPI(title="Becoming LLM gateway")
class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None,max_length=100000)
    tool_calls: list[dict] | None = Field(default=None,max_length=16)
    tool_call_id: str | None = Field(default=None,max_length=128)

    @model_validator(mode="after")
    def validate_message(self):
        if self.role in ("system", "user", "tool") and not self.content:
            raise ValueError("Message content is required")
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("Tool message requires tool_call_id")
        if self.role == "assistant" and not self.content and not self.tool_calls:
            raise ValueError("Assistant message requires content or tool_calls")
        return self

class Completion(BaseModel):
    messages: list[Message] = Field(min_length=1,max_length=60)
    tools: list[dict] | None = Field(default=None,max_length=32)
    tool_choice: str | dict | None = None

    @model_validator(mode="after")
    def validate_tools(self):
        if self.tools is not None:
            names=set()
            for item in self.tools:
                if not isinstance(item,dict) or set(item)!={"type","function"} or item.get("type")!="function":
                    raise ValueError("Invalid tool definition")
                fn=item.get("function")
                if not isinstance(fn,dict) or not isinstance(fn.get("name"),str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",fn["name"]):
                    raise ValueError("Invalid tool name")
                if fn["name"] in names:
                    raise ValueError("Duplicate tool name")
                names.add(fn["name"])
                if not isinstance(fn.get("description",""),str) or len(fn.get("description",""))>2048:
                    raise ValueError("Invalid tool description")
                schema=fn.get("parameters")
                if not isinstance(schema,dict) or schema.get("type")!="object":
                    raise ValueError("Tool parameters must be an object schema")
                if len(json.dumps(schema))>12000:
                    raise ValueError("Tool schema too large")
        if isinstance(self.tool_choice,str) and self.tool_choice not in ("auto","none","required"):
            raise ValueError("Invalid tool_choice")
        if isinstance(self.tool_choice,dict):
            if set(self.tool_choice)!={"type","function"} or self.tool_choice.get("type")!="function" or not isinstance(self.tool_choice.get("function"),dict) or set(self.tool_choice["function"])!={"name"}:
                raise ValueError("Invalid named tool_choice")
        return self

class ImageGenerationRequest(BaseModel):
    prompt: str = Field(min_length=1,max_length=4000)
    size: Literal["1024x1024","1024x1536","1536x1024"] = "1024x1024"

@app.get("/health")
def health(): return {"ok":True}

@app.post("/v1/llm/complete")
def llm(request: Completion):
    if sum(len(m.content or '') for m in request.messages)>500000:
        raise HTTPException(413,"Context too large")
    try:
        base=os.environ.get("BECOMING_BASE_URL",os.environ.get("BECOMING_MODEL_BASE_URL","https://api.openai.com/v1"))
        key=os.environ.get("BECOMING_API_KEY") or os.environ.get("BECOMING_MODEL_API_KEY")
        model=os.environ.get("BECOMING_MODEL")
        parsed=urlparse(base)
        if not key or not model or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (parsed.scheme=="https" or (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1","::1"))):
            raise HTTPException(503,"Model not configured")
        payload={"model":model,"messages":[m.model_dump(exclude_none=True) for m in request.messages]}
        if request.tools is not None: payload["tools"]=request.tools
        if request.tool_choice is not None: payload["tool_choice"]=request.tool_choice
        req=Request(base.rstrip("/")+"/chat/completions",data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
        with build_opener(NoRedirect()).open(req,timeout=90) as response:
            result=json.load(response)
        choice=result["choices"][0]
        message=choice["message"]
        content=message.get("content") or ""
        tool_calls=message.get("tool_calls") or []
        if not isinstance(content,str) or len(content)>64000 or not isinstance(tool_calls,list) or len(tool_calls)>16 or (not content.strip() and not tool_calls):
            raise ValueError("Invalid model response")
        for call in tool_calls:
            if not isinstance(call,dict):
                raise ValueError("Invalid tool call response")
            fn=call.get("function")
            if not isinstance(call.get("id"),str) or call.get("type")!="function" or not isinstance(fn,dict) or not isinstance(fn.get("name"),str) or not isinstance(fn.get("arguments"),str) or len(fn["arguments"])>12000:
                raise ValueError("Invalid tool call response")
        return {"text":content.strip(),"tool_calls":tool_calls,"finish_reason":choice.get("finish_reason"),"usage":result.get("usage")}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,"Upstream model request failed") from None


@app.post("/v1/llm/stream")
def llm_stream(request: Completion):
    """Forward provider SSE chunks without interpreting or storing conversation data."""
    if sum(len(m.content or '') for m in request.messages)>500000:
        raise HTTPException(413,"Context too large")
    try:
        base=os.environ.get("BECOMING_BASE_URL",os.environ.get("BECOMING_MODEL_BASE_URL","https://api.openai.com/v1"))
        key=os.environ.get("BECOMING_API_KEY") or os.environ.get("BECOMING_MODEL_API_KEY")
        model=os.environ.get("BECOMING_MODEL")
        parsed=urlparse(base)
        if not key or not model or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (parsed.scheme=="https" or (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1","::1"))):
            raise HTTPException(503,"Model not configured")
        payload={"model":model,"messages":[m.model_dump(exclude_none=True) for m in request.messages],"stream":True}
        if request.tools is not None: payload["tools"]=request.tools
        if request.tool_choice is not None: payload["tool_choice"]=request.tool_choice
        req=Request(base.rstrip("/")+"/chat/completions",data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","Accept":"text/event-stream"},method="POST")
        upstream=build_opener(NoRedirect()).open(req,timeout=90)
        if upstream.headers.get_content_type()!="text/event-stream":
            upstream.close()
            raise HTTPException(502,"Upstream did not return an SSE stream")
        def chunks():
            try:
                while True:
                    chunk=upstream.readline()
                    if not chunk:
                        break
                    yield chunk
            finally:
                upstream.close()
        return StreamingResponse(chunks(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no"})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,"Upstream model stream failed") from None

class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1,max_length=32)

@app.post("/v1/llm/images")
def generate_image(request: ImageGenerationRequest):
    """Optional OpenAI-compatible image generation proxy; image credentials stay in Python."""
    try:
        base=os.environ.get("BECOMING_IMAGE_BASE_URL",os.environ.get("BECOMING_BASE_URL",os.environ.get("BECOMING_MODEL_BASE_URL","https://api.openai.com/v1")))
        key=os.environ.get("BECOMING_IMAGE_API_KEY") or os.environ.get("BECOMING_API_KEY") or os.environ.get("BECOMING_MODEL_API_KEY")
        model=os.environ.get("BECOMING_IMAGE_MODEL")
        parsed=urlparse(base)
        if not key or not model or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not (parsed.scheme=="https" or (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1","::1"))):
            raise HTTPException(503,"Image generation not configured")
        payload={"model":model,"prompt":request.prompt,"size":request.size,"n":1}
        req=Request(base.rstrip("/")+"/images/generations",data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},method="POST")
        with build_opener(NoRedirect()).open(req,timeout=180) as response:
            result=json.load(response)
        rows=result.get("data")
        if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict) or not isinstance(rows[0].get("b64_json"),str):
            raise ValueError("Provider must return one base64-encoded image")
        encoded=rows[0]["b64_json"]
        if len(encoded)>20000000:
            raise ValueError("Generated image is too large")
        raw=base64.b64decode(encoded,validate=True)
        if not raw or len(raw)>15000000:
            raise ValueError("Generated image is too large")
        if raw.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):
            mime="image/png"
        elif raw.startswith(b"\\xff\\xd8\\xff"):
            mime="image/jpeg"
        elif len(raw)>12 and raw[:4]==b"RIFF" and raw[8:12]==b"WEBP":
            mime="image/webp"
        else:
            raise ValueError("Unsupported generated image format")
        return {"image_base64":encoded,"mime_type":mime,"revised_prompt":rows[0].get("revised_prompt")}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(502,"Upstream image generation failed") from None


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
