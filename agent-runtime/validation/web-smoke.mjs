import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Agent,Gateway} from '../agent.mjs';
import {Store} from '../store.mjs';

const gatewayUrl=process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000';
const directory=mkdtempSync(join(tmpdir(),'becoming-web-live-'));
const store=new Store(join(directory,'agent.sqlite3'));
const model=new Gateway(gatewayUrl);
const agent=new Agent(store,model,{historyTurns:0});
const tokens=[];
const started=performance.now();
try{
  const turn=await agent.replyStream(
    '请用中文简短说明，你可以怎样陪伴一个人进行日常交流？只用两三句话，不要输出 JSON。',
    'default',
    {requestId:randomUUID(),onToken:token=>tokens.push(token)}
  );
  const answer=tokens.join('');
  assert.ok(tokens.length>0,'No streamed token deltas were received');
  assert.ok(answer.trim().length>0,'The streamed answer was empty');
  assert.equal(turn.assistant,answer.trim(),'Persisted answer differs from streamed output');
  assert.equal(store.history(10).length,1,'Completed turn was not persisted');
  console.log(JSON.stringify({
    status:'passed',
    test:'real-model-web-stream',
    streamed_chunks:tokens.length,
    answer_characters:turn.assistant.length,
    elapsed_ms:Math.round(performance.now()-started),
    persisted_turn:true
  }));
}catch(error){
  console.error(JSON.stringify({status:'failed',test:'real-model-web-stream',error:error.message,elapsed_ms:Math.round(performance.now()-started)}));
  process.exitCode=1;
}finally{
  store.close();
  rmSync(directory,{recursive:true,force:true});
}
