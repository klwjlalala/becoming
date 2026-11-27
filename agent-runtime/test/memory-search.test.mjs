import test from 'node:test';
import assert from 'node:assert/strict';
import {Store} from '../store.mjs';
import {HistoricalMemory,parsePlan,candidatePool,hybridPool} from '../memory-search.mjs';
const plan={topics:['职业'],start:null,end:null,include_history:false};
test('strict plan dates, multiple topics, oldest diverse candidate',()=>{
 assert.throws(()=>parsePlan(JSON.stringify({...plan,start:'2025-02-29'})));
 assert.throws(()=>parsePlan(JSON.stringify({...plan,start:'2026-01-01',end:'2025-01-01'})));
 const records=Array.from({length:60},(_,i)=>({id:i+1,key:'topic',quote:i?'职业':'自由',recorded_at:new Date(Date.UTC(2025,0,i+1)).toISOString()}));
 const pool=candidatePool(records,['职业'],40);assert.equal(pool.length,40);assert.ok(pool.some(m=>m.id===1));assert.equal(new Set(pool.map(m=>m.id)).size,40);
});
test('historical retrieval respects revision state, date range and invalid IDs',async()=>{
 const store=new Store(':memory:');let p={...plan},bad=false;
 const model={complete:async messages=>{const body=JSON.parse(messages[1].content);if(body.today_utc)return JSON.stringify(p);return JSON.stringify(bad?[9999]:body.candidates.slice(0,body.limit).map(m=>m.id));}};
 const memory=new HistoricalMemory(store,model);
 const t1=store.append('我的职业是教师','ok');store.db.prepare('UPDATE turns SET created_at=? WHERE id=?').run('2025-01-01T00:00:00Z',t1.id);
 const [old]=memory.write(t1.id,[{key:'职业',category:'fact',quote:t1.user}]);
 const t2=store.append('更正，我的职业是工程师','ok');store.db.prepare('UPDATE turns SET created_at=? WHERE id=?').run('2025-02-01T00:00:00Z',t2.id);
 memory.write(t2.id,[{key:'职业',category:'fact',quote:t2.user,replaces:old}]);
 assert.equal((await memory.retrieve('职业')).length,1);p={...p,include_history:true,start:'2025-01-01',end:'2025-01-01'};
 const out=await memory.retrieve('以前的职业');assert.equal(out[0].id,old);assert.equal(out[0].active,0);
 bad=true;await assert.rejects(memory.retrieve('职业'));store.close();
});
test('improved scan is bounded and embedding failure falls back',async()=>{
 const store=new Store(':memory:');let calls=0;
 const model={complete:async messages=>{const b=JSON.parse(messages[1].content);if(b.today_utc)return JSON.stringify(plan);calls++;assert.ok(b.candidates.length<=40);return JSON.stringify(b.candidates.slice(0,1).map(m=>m.id));}};
 const memory=new HistoricalMemory(store,model,{improved:true,embedder:{embed:async()=>{throw Error('unavailable');}}});
 for(let i=0;i<50;i++){const t=store.append('职业记录'+i,'ok');memory.write(t.id,[{key:'key'+i,category:'fact',quote:t.user}]);}
 await memory.retrieve('职业');assert.equal(memory.lastSearch.embedding_fallback,true);assert.equal(memory.lastSearch.batches.length,2);assert.equal(calls,3);store.close();
});
test('embedding hybrid pool validates dimension and mixes rankings',async()=>{
 const items=Array.from({length:45},(_,i)=>({id:i+1,key:'k'+i,quote:'记录'+i,recorded_at:'2025-01-01'}));
 const pool=await hybridPool(items,'query',[],{embed:async inputs=>inputs.map((_,i)=>i===0||i===1?[1,0]:[0,1])},40);
 assert.equal(pool.length,40);assert.equal(pool[0].id,1);
 await assert.rejects(hybridPool(items,'query',[],{embed:async inputs=>inputs.map((_,i)=>i===0?[1,0]:[1])},40));
});
