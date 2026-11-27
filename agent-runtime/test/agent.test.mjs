import test from 'node:test';
import assert from 'node:assert/strict';
import {Store} from '../store.mjs';
import {Agent,SyncWorker} from '../agent.mjs';
test('history, failed turn and ordered model calls',async()=>{
 const store=new Store(':memory:');const requests=[];
 const agent=new Agent(store,{post:async(p,r)=>{requests.push(r);if(r.messages.at(-1).content==='fail')throw Error('offline');return {text:'ok'};}});
 await agent.reply('first');await assert.rejects(agent.reply('fail'));await agent.reply('second');
 assert.equal(store.history().length,2);assert.equal(requests[2].messages[1].content,'first');assert.equal(store.pending().length,2);store.close();
});
test('sync failure retains local data, retry and duplicate pull converge',async()=>{
 const store=new Store(':memory:');const t=store.append('a','b');let fail=true;
 const worker=new SyncWorker(store,{post:async()=>{if(fail)throw Error('offline');return {ack:[t.id],turns:[t],cursor:1};}});
 await worker.tick();assert.equal(store.pending().length,1);fail=false;await worker.tick();await worker.tick();
 assert.equal(store.pending().length,0);assert.equal(store.history().length,1);assert.equal(store.cursor(),1);store.close();
});
test('conflicting remote data rolls back ack and cursor',()=>{
 const store=new Store(':memory:');const t=store.append('a','b');
 assert.throws(()=>store.applySync([t.id],[{...t,user:'different'}],1));
 assert.equal(store.pending().length,1);assert.equal(store.cursor(),0);store.close();
});
