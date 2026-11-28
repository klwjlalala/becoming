import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {setTimeout as delay} from 'node:timers/promises';
import {Agent,Gateway} from '../agent.mjs';
import {Store} from '../store.mjs';

async function withServer(handler,run){
  const server=createServer(handler);
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  try{return await run('http://127.0.0.1:'+server.address().port);}
  finally{
    server.closeAllConnections?.();
    await new Promise(resolve=>server.close(resolve));
  }
}
async function collect(iterable){
  const result=[];for await(const token of iterable)result.push(token);return result;
}
const chunk=(content,finish=null)=>'data: '+JSON.stringify({choices:[{delta:content===null?{}:{content},finish_reason:finish}]})+'\n\n';

test('Gateway parses fragmented UTF-8 SSE frames and the OpenAI completion marker',async()=>{
  await withServer(async(_req,res)=>{
    res.writeHead(200,{'Content-Type':'text/event-stream','Connection':'close'});
    const payload=Buffer.from(chunk(null)+chunk('你好，')+chunk('朋友。')+chunk(null,'stop')+'data: [DONE]\r\n\r\n');
    for(let i=0;i<payload.length;i+=5){res.write(payload.subarray(i,i+5));await delay(1);}
    res.end();
  },async url=>{
    const tokens=await collect(new Gateway(url).stream([{role:'user',content:'hi'}]));
    assert.deepEqual(tokens,['你好，','朋友。']);
  });
});

test('Gateway accepts a finish_reason terminal chunk when a provider omits [DONE]',async()=>{
  await withServer((_req,res)=>{
    res.writeHead(200,{'Content-Type':'text/event-stream','Connection':'close'});
    res.end(chunk('完整回复。')+chunk(null,'stop'));
  },async url=>{
    assert.deepEqual(await collect(new Gateway(url).stream([{role:'user',content:'hi'}])),['完整回复。']);
  });
});

test('Gateway rejects upstream SSE error events rather than persisting partial text',async()=>{
  await withServer((_req,res)=>{
    res.writeHead(200,{'Content-Type':'text/event-stream','Connection':'close'});
    res.end(chunk('不完整内容')+'event: error\ndata: {"error":{"message":"provider unavailable"}}\n\n');
  },async url=>{
    await assert.rejects(()=>collect(new Gateway(url).stream([{role:'user',content:'hi'}])),/Upstream model stream error/);
  });
});

test('Gateway rejects truncated streams that have no terminal marker',async()=>{
  await withServer((_req,res)=>{
    res.writeHead(200,{'Content-Type':'text/event-stream','Connection':'close'});
    res.end(chunk('不完整内容'));
  },async url=>{
    await assert.rejects(()=>collect(new Gateway(url).stream([{role:'user',content:'hi'}])),/ended before completion/);
  });
});

test('Gateway rejects non-SSE responses',async()=>{
  await withServer((_req,res)=>{
    res.writeHead(200,{'Content-Type':'application/json','Connection':'close'});
    res.end(JSON.stringify({error:'not a stream'}));
  },async url=>{
    await assert.rejects(()=>collect(new Gateway(url).stream([{role:'user',content:'hi'}])),/did not return an SSE stream/);
  });
});

test('Gateway stream cancellation propagates to the reader',async()=>{
  await withServer(async(_req,res)=>{
    res.writeHead(200,{'Content-Type':'text/event-stream','Connection':'close'});
    res.write(chunk('第一段'));
    await delay(500);
    if(!res.destroyed){res.write(chunk('第二段')+chunk(null,'stop'));res.end();}
  },async url=>{
    const controller=new AbortController(),stream=new Gateway(url).stream([{role:'user',content:'hi'}],{signal:controller.signal});
    const first=await stream.next();assert.deepEqual(first,{value:'第一段',done:false});
    controller.abort();
    await assert.rejects(()=>stream.next(),error=>error.name==='AbortError');
  });
});

test('Agent never persists partial text after an upstream SSE error',async()=>{
  const store=new Store(':memory:');
  try{
    await withServer((_req,res)=>{
      res.writeHead(200,{'Content-Type':'text/event-stream','Connection':'close'});
      res.end(chunk('这是一段未完成的回复')+'event: error\ndata: {"error":{"message":"provider failed"}}\n\n');
    },async url=>{
      const agent=new Agent(store,new Gateway(url),{historyTurns:0});
      await assert.rejects(()=>agent.replyStream('请回复'));
      assert.equal(store.history().length,0);
    });
  }finally{store.close();}
});
