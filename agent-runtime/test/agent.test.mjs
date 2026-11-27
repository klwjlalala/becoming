import test from 'node:test';
import assert from 'node:assert/strict';
import {Store} from '../store.mjs';
import {Agent,BackgroundWorker} from '../agent.mjs';
import {LongMemory,completeQuote} from '../memory.mjs';
test('ordered replies and failure do not persist incomplete turns',async()=>{
 const store=new Store(':memory:'),calls=[];
 const agent=new Agent(store,{complete:async messages=>{calls.push(messages);if(messages.at(-1).content==='fail')throw Error('offline');return 'ok';}});
 await agent.reply('first');await assert.rejects(agent.reply('fail'));await agent.reply('second');
 assert.equal(store.history().length,2);assert.equal(calls[2][1].content,'first');store.close();
});
test('real agent / background extract / recall / revision / forget',async()=>{
 const store=new Store(':memory:');let replacement=null;let context='';
 const model={complete:async messages=>{
  if(messages[0].content.includes('你是记忆提取器')){
   const user=JSON.parse(messages[1].content).current_user_message;
   return JSON.stringify([{key:'职业',category:'fact',quote:user,replaces:replacement}]);
  }context=messages[0].content;return '收到';
 }};
 const memory=new LongMemory(store,model),agent=new Agent(store,model,{memory});
 const worker=new BackgroundWorker(store,{'long_memory.extract':id=>memory.extract(id)});
 const t=await agent.reply('我的职业是教师');
 assert.equal(store.jobs(t.id)[0].status,'pending');assert.equal(memory.list().length,0);
 await worker.tick();assert.equal(store.jobs(t.id)[0].status,'done');assert.equal(memory.list().length,1);
 await memory.extract(t.id);assert.equal(memory.list().length,1);
 replacement=memory.list()[0].id;
 const next=await agent.reply('更正，我的职业是工程师');assert.ok(context.includes('我的职业是教师'));await worker.tick();
 assert.equal(memory.list()[0].quote,'更正，我的职业是工程师');assert.equal(memory.list(false).length,2);
 assert.equal(memory.forget('职业'),2);assert.equal(memory.list().length,0);assert.deepEqual(memory.blockedKeys(),['职业']);store.close();
});
test('source boundaries and credentials are rejected; failed jobs retry finitely',async()=>{
 assert.equal(completeQuote('我喜欢跑步','如果有空，我喜欢跑步'),false);
 const store=new Store(':memory:'),model={complete:async()=>'{invalid'},memory=new LongMemory(store,model);
 const t=store.append('我喜欢跑步','ok',['long_memory.extract']);
 assert.throws(()=>memory.write(t.id,[{key:'运动',category:'subjective',quote:'喜欢跑步'}]));
 const worker=new BackgroundWorker(store,{'long_memory.extract':id=>memory.extract(id)});
 await worker.tick();await worker.tick();await worker.tick();
 assert.equal(store.jobs(t.id)[0].status,'failed');assert.equal(store.jobs(t.id)[0].attempts,3);assert.equal(await worker.tick(),false);
 store.close();
});
