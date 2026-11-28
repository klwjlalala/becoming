import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {Store} from '../store.mjs';
import {Agent,BackgroundWorker} from '../agent.mjs';
import {LongMemory} from '../memory.mjs';
import {HistoricalMemory} from '../memory-search.mjs';
import {PersonalUnderstanding} from '../understanding.mjs';
const op=(extra={})=>({operation:'CREATE',claim_ref:'c1',claim_id:null,expected_version:null,content:'用户重视自由',dimension:'values',basis:'ai_inference',scope:{},temporal_scope:'unknown',evidence:[{ref:'e1',relation:'support'}],reason:'证据更新',...extra});
const proposal=(quote,operation=op(),kind='direct_statement')=>JSON.stringify({evidence:[{ref:'e1',turn_index:0,quote,kind,event_time:null}],operations:[operation],confirmation:null});
test('zero recent history isolates memory retrieval; disabled features do not schedule',async()=>{
 const s=new Store(':memory:');let calls=[];
 const m={complete:async msgs=>{calls.push(msgs);return '答复';}};
 const a=new Agent(s,m,{historyTurns:0});
 await a.reply('第一条内容');const t=await a.reply('第二条内容');
 assert.equal(calls[1].length,2);assert.deepEqual(s.jobs(t.id),[]);assert.throws(()=>new Agent(s,m,{historyTurns:-1}));s.close();
});
test('restart reconciles completed receipts and exhausts interrupted retries',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'becoming-regression-'));const path=join(dir,'a.db');let s;
 try{
 s=new Store(path);let calls=0;const model={complete:async()=>{calls++;return '[{"key":"职业","category":"fact","quote":"我的职业是教师","replaces":null}]';}};
 let mem=new LongMemory(s,model);const t=s.append('我的职业是教师','ok',['long_memory.extract']);
 const job=s.claim();await mem.extract(t.id);s.close();s=new Store(path);mem=new LongMemory(s,model);
 assert.equal(s.jobs(t.id)[0].status,'done');assert.equal(s.jobs(t.id)[0].id,job.id);await mem.extract(t.id);assert.equal(calls,1);
 const failed=s.append('另一条','ok',['long_memory.extract']);s.db.prepare("UPDATE background_jobs SET status='running',attempts=3 WHERE turn_id=?").run(failed.id);
 s.close();s=new Store(path);assert.equal(s.jobs(failed.id)[0].status,'failed');assert.equal(s.claim(),null);
 }finally{s?.close();rmSync(dir,{recursive:true,force:true});}
});
test('urgent personal correction is prioritized and backlog can batch',async()=>{
 const s=new Store(':memory:');let input;
 const model={complete:async messages=>{if(messages[0].content.includes('你是个人理解更新引擎')){input=JSON.parse(messages[1].content);return '{"evidence":[],"operations":[],"confirmation":null}';}return 'ok';}};
 const u=new PersonalUnderstanding(s,model),m=new LongMemory(s,model),a=new Agent(s,model,{understanding:u,memory:m});
 await a.reply('一般交流');const correction=await a.reply('你理解错了，我的目标已经改变');
 const w=new BackgroundWorker(s,{'personal_understanding.process':id=>u.processTurn(id),'long_memory.extract':id=>m.extract(id)});
 await w.tick();assert.equal(input.turns[0].source_turn_id,correction.id);assert.equal(input.turns.length,2);
 assert.equal(s.jobs(correction.id).find(j=>j.kind==='personal_understanding.process').status,'done');s.close();
});
test('revision, reinforcement, dispute, rejection and expire preserve history',async()=>{
 const s=new Store(':memory:');let raw;const u=new PersonalUnderstanding(s,{complete:async()=>raw});
 async function update(user,fn){const t=s.append(user,'好的');raw=fn(user);await u.processTurn(t.id);}
 await update('我重视自由',q=>proposal(q));let c=u.list()[0],id=c.id;
 const revise=(operation,content,relation='support')=>op({operation,claim_ref:null,claim_id:id,expected_version:u.current(id).version,content,evidence:[{ref:'e1',relation}]});
 await update('我也重视自由支配时间',q=>proposal(q,revise('REINFORCE',c.content)));assert.equal(u.current(id).support_level,'medium');
 await update('我希望有条件地自由安排时间',q=>proposal(q,revise('REFINE','用户重视有条件的自由')));assert.equal(u.current(id).support_level,'low');
 await update('我现在更重视稳定',q=>proposal(q,revise('DISPUTE','用户重视有条件的自由','counter')));assert.equal(u.current(id).status,'disputed');
 await update('你理解错了，我不认同这个概括',q=>proposal(q,revise('REJECT','用户重视有条件的自由','counter'),'correction'));assert.equal(u.current(id).status,'rejected');assert.equal(u.list().length,0);
 assert.deepEqual(u.revisions(id).map(r=>r.operation),['CREATE','REINFORCE','REFINE','DISPUTE','REJECT']);assert.equal(u.history(id).length,5);s.close();
});
test('ambiguous memory replacement is rejected without failing background extraction',async()=>{
 const s=new Store(':memory:');let calls=0;const m=new LongMemory(s,{complete:async()=>{calls++;return '[{"key":"偏好","category":"subjective","quote":"我喜欢和朋友交流","replaces":null}]';}});
 const old=s.append('我喜欢安静的地方','ok');const [id]=m.write(old.id,[{key:'偏好',category:'subjective',quote:old.user}]);
 const next=s.append('我喜欢和朋友交流','ok');const result=await m.extract(next.id);
 assert.deepEqual(result,{written:[],rejected:1});assert.equal(m.list()[0].id,id);assert.ok(m.receipt(next.id));
 await m.extract(next.id);assert.equal(calls,1);s.close();
});
test('long-memory retrieval suppresses third-party, transient mood, and listen-only context',async()=>{
 const s=new Store(':memory:');const m=new LongMemory(s,{complete:async()=>''});
 const seed=s.append('我暂时不想冒险辞职。','ok');
 const [id]=m.write(seed.id,[{key:'career_risk_preference',category:'subjective',quote:'我暂时不想冒险辞职'}]);
 const a=new Agent(s,{complete:async()=> '我听到了。'},{memory:m,historyTurns:12});
 const cases=[
  ['我朋友最近说他想辞职创业，我只是听他吐槽。','third_party_only'],
  ['今天有点烦，什么都不想做，明天应该就好了。','transient_mood'],
  ['我最近有点迷茫，先别给我方案，我只是想说说。','listen_only']
 ];
 for(const [query,reason] of cases){
  const turn=await a.reply(query);
  assert.deepEqual(turn.event.retrieved_memory_ids,[]);
  assert.equal(turn.event.memory_search.query_mode,'suppressed');
  assert.equal(turn.event.memory_search.suppression_reason,reason);
 }
 const personal=await a.reply('我自己也在考虑是否辞职，但暂时不想冒险。');
 assert.ok(personal.event.retrieved_memory_ids.includes(id));
 s.close();
});
