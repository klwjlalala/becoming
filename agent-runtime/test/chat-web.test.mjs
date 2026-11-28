import test from 'node:test';
import assert from 'node:assert/strict';
import {Store} from '../store.mjs';
import {Agent} from '../agent.mjs';

test('streamed Agent reply emits deltas and persists only the completed turn',async()=>{
  const store=new Store(':memory:'),seen=[];
  const model={async *stream(){yield '你好，';yield '我们可以慢慢聊。';}};
  const agent=new Agent(store,model);
  const turn=await agent.replyStream('最近有点迷茫','default',{requestId:'stream-request-0001',onToken:t=>seen.push(t)});
  assert.deepEqual(seen,['你好，','我们可以慢慢聊。']);
  assert.equal(turn.assistant,'你好，我们可以慢慢聊。');
  assert.equal(store.history().length,1);
  store.close();
});

test('aborted model stream does not persist an incomplete turn',async()=>{
  const store=new Store(':memory:');
  const model={async *stream(_messages,{signal}={}){
    yield '部分内容';
    await new Promise((resolve,reject)=>{
      if(signal?.aborted){const e=new Error('cancelled');e.name='AbortError';reject(e);return;}
      signal?.addEventListener('abort',()=>{const e=new Error('cancelled');e.name='AbortError';reject(e);},{once:true});
    });
    yield '不应出现';
  }};
  const agent=new Agent(store,model),controller=new AbortController();
  const pending=agent.replyStream('请回复','default',{signal:controller.signal,requestId:'stream-request-0002'});
  await new Promise(resolve=>setTimeout(resolve,0));
  controller.abort();
  await assert.rejects(pending,error=>error.name==='AbortError');
  assert.equal(store.history().length,0);
  store.close();
});

test('retrying the same request ID returns the original turn without another model call',async()=>{
  const store=new Store(':memory:');let calls=0;
  const agent=new Agent(store,{complete:async()=>{calls++;return '已完成';}});
  const first=await agent.reply('你好','default',{requestId:'retry-request-0001'});
  const second=await agent.reply('你好','default',{requestId:'retry-request-0001'});
  assert.equal(calls,1);assert.equal(first.id,second.id);assert.equal(store.history().length,1);
  store.close();
});

test('history paging, around-message navigation and exact search are bounded to one conversation',()=>{
  const store=new Store(':memory:');
  const ids=[];
  for(let i=0;i<5;i++)ids.push(store.append('第'+i+'条消息','回复'+i).id);
  const latest=store.historyPage(2);
  assert.equal(latest.turns.length,2);assert.equal(latest.has_more,true);
  const older=store.historyPage(2,'default',latest.before);
  assert.equal(older.turns.length,2);assert.equal(older.turns.at(-1).user,'第2条消息');
  const around=store.historyAround(ids[1],4);
  assert.ok(around.turns.some(t=>t.id===ids[1]));
  assert.equal(store.search('第3条').length,1);
  assert.equal(store.search('不存在').length,0);
  store.close();
});
