import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer as createHttpServer} from 'node:http';
import {createServer as createNetServer} from 'node:net';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';

async function freePort(){
  const server=createNetServer();
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const port=server.address().port;
  await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));
  return port;
}
test('Web shell serves one long conversation with streamed chat and idempotent retries',async()=>{
  const dir=mkdtempSync(join(tmpdir(),'becoming-web-'));
  const gatewayCalls={count:0};
  const gateway=createHttpServer((req,res)=>{
    if(req.url==='/v1/llm/complete'){
      gatewayCalls.count++;
      res.writeHead(200,{'Content-Type':'application/json'});
      res.end(JSON.stringify({text:'你好，这里是测试回复。',tool_calls:[],finish_reason:'stop'}));
      return;
    }
    if(req.url!=='/v1/llm/stream'){res.writeHead(404);res.end();return;}
    gatewayCalls.count++;
    res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache'});
    const chunks=['你好，','这里是测试回复。'];
    for(const content of chunks)res.write('data: '+JSON.stringify({choices:[{delta:{content}}]})+'\n\n');
    res.end('data: [DONE]\n\n');
  });
  await new Promise(resolve=>gateway.listen(0,'127.0.0.1',resolve));
  const gatewayPort=gateway.address().port,port=await freePort();
  const runtimeDir=fileURLToPath(new URL('..',import.meta.url));
  const base='http://127.0.0.1:'+port;
  const child=spawn(process.execPath,['server.mjs'],{
    cwd:runtimeDir,stdio:'ignore',
    env:{...process.env,BECOMING_LOCAL_PORT:String(port),BECOMING_LOCAL_DB:join(dir,'agent.sqlite3'),BECOMING_LOCAL_GROWTH_DB:join(dir,'growth.sqlite3'),BECOMING_GATEWAY:'http://127.0.0.1:'+gatewayPort,BECOMING_ENABLE_LONG_MEMORY:'0',BECOMING_ENABLE_PERSONAL_UNDERSTANDING:'0'}
  });
  try{
    let ready=false;
    for(let i=0;i<50;i++){
      try{const response=await fetch(base+'/api/status');if(response.ok){ready=true;break;}}catch{}
      await delay(50);
    }
    assert.equal(ready,true,'local Node server did not become ready');
    const page=await fetch(base+'/');
    assert.equal(page.status,200);
    assert.match(await page.text(),/AI 好友/);
    assert.match(await (await fetch(base+'/app.js')).text(),/api\/chat\/stream/);
    assert.equal((await fetch(base+'/api/history').then(r=>r.json())).turns.length,0);
    assert.equal((await fetch(base+'/api/conversations',{method:'POST',headers:{'content-type':'application/json','origin':base},body:JSON.stringify({title:'新会话'})})).status,404);

    const requestId='bcb56b1e-57f8-4f58-9c55-0123456789ab';
    const payload={text:'你好',request_id:requestId};
    const first=await fetch(base+'/api/chat/stream',{method:'POST',headers:{'content-type':'application/json','origin':base},body:JSON.stringify(payload)});
    assert.equal(first.status,200);
    const stream=await first.text();
    assert.match(stream,/event: token/);
    assert.match(stream,/event: done/);
    assert.match(stream,/这里是测试回复/);
    const history=await fetch(base+'/api/history').then(r=>r.json());
    assert.equal(history.turns.length,1);
    assert.equal(history.turns[0].user,'你好');
    assert.equal(history.turns[0].assistant,'你好，这里是测试回复。');

    const retry=await fetch(base+'/api/chat/stream',{method:'POST',headers:{'content-type':'application/json','origin':base},body:JSON.stringify(payload)});
    const retryText=await retry.text();
    assert.match(retryText,/event: done/);
    assert.doesNotMatch(retryText,/event: token/);
    assert.equal(gatewayCalls.count,1);
    assert.equal((await fetch(base+'/api/history').then(r=>r.json())).turns.length,1);
    const receipt=await fetch(base+'/api/requests/'+requestId).then(r=>r.json());
    assert.equal(receipt.turn.user,'你好');
  }finally{
    child.kill('SIGTERM');
    await new Promise(resolve=>setTimeout(resolve,80));
    await new Promise(resolve=>gateway.close(resolve));
    rmSync(dir,{recursive:true,force:true});
  }
});
