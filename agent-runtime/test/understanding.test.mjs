import test from 'node:test';
import assert from 'node:assert/strict';
import {Store} from '../store.mjs';
import {Agent,BackgroundWorker} from '../agent.mjs';
import {PersonalUnderstanding,parseProposal} from '../understanding.mjs';
const op=(extra={})=>({operation:'CREATE',claim_ref:'c1',claim_id:null,expected_version:null,content:'用户重视自由',dimension:'values',basis:'ai_inference',scope:{},temporal_scope:'unknown',evidence:[{ref:'e1',relation:'support'}],prior_evidence:[],reason:'用户表达偏好',...extra});
const proposal=(quote,extra={})=>({evidence:[{ref:'e1',turn_index:0,quote,kind:'direct_statement',event_time:null}],operations:[op()],confirmation:null,...extra});
test('claim source, version, confirmation, rejection and retrieval',async()=>{
 const store=new Store(':memory:');let raw='';
 const model={complete:async m=>m[0].content.includes('你是个人理解更新引擎')?raw:'你更重视自由吗？'};
 const u=new PersonalUnderstanding(store,model),agent=new Agent(store,model,{understanding:u});
 const worker=new BackgroundWorker(store,{'personal_understanding.process':id=>u.processTurn(id)});
 const first=await agent.reply('我希望自由支配时间');
 raw=JSON.stringify(proposal(first.user,{confirmation:{claim_id:null,claim_ref:'c1',expected_version:1,turn_index:0,question:'你更重视自由吗？'}}));
 await worker.tick();assert.equal(store.jobs(first.id)[0].status,'done');
 const c=u.list()[0];assert.equal(c.support_level,'low');assert.equal(u.retrieve('人生意义')[0].id,c.id);
 assert.equal(u.retrieve('先别给我方案').length,0);
 const second=await agent.reply('是的');assert.deepEqual(second.event.confirmed_claim_ids,[c.id]);
 assert.equal(u.list()[0].user_validation,'confirmed');assert.equal(u.list()[0].version,2);assert.equal(u.history(c.id).length,2);assert.equal(u.revisions(c.id).at(-1).operation,'CONFIRM');
 store.close();
});
test('invalid reference, fabricated evidence and duplicate JSON rejected before writes',()=>{
 const turns=[{user_text:'我喜欢阅读',assistant_text:'好的'}];
 assert.throws(()=>parseProposal(JSON.stringify(proposal('我喜欢跑步')),turns,[]));
 assert.throws(()=>parseProposal(JSON.stringify(proposal('我喜欢阅读',{operations:[op({operation:'REFINE',claim_ref:null,claim_id:'unknown',expected_version:1})]})),turns,[]));
 assert.throws(()=>parseProposal('{"evidence":[],"evidence":[],"operations":[]}',turns,[]));
});
test('background durable jobs and source deletion cascade',async()=>{
 const store=new Store(':memory:'),u=new PersonalUnderstanding(store,{complete:async()=>JSON.stringify(proposal('我喜欢阅读'))});
 const t=store.append('我喜欢阅读','好的',['personal_understanding.process']);await u.processTurn(t.id);await u.processTurn(t.id);assert.equal(u.list().length,1);
 store.db.prepare('DELETE FROM turns WHERE id=?').run(t.id);assert.equal(u.list().length,0);store.close();
});

test('invalid supersede relation leaves prior version intact and next attempt gets corrective feedback',async()=>{
 const s=new Store(':memory:');let calls=0,raw,sys;
 const model={complete:async msgs=>{calls++;sys=msgs[0].content;return raw;}},u=new PersonalUnderstanding(s,model);
 const first=s.append('我重视创业','好的');raw=JSON.stringify(proposal(first.user));await u.processTurn(first.id);
 const c=u.list()[0],oldId=u.history(c.id)[0].evidence[0].id;
 const next=s.append('更正一下：我真正重视的是选择权','好的');
 const p=proposal(next.user,{evidence:[{ref:'e1',turn_index:0,quote:next.user,kind:'correction',event_time:null}],operations:[op({operation:'SUPERSEDE',claim_ref:null,claim_id:c.id,expected_version:1,content:'用户重视选择权',prior_evidence:[{evidence_id:oldId,relation:'counter'}]})]});
 raw=JSON.stringify(p);await assert.rejects(u.processTurn(next.id),/Missing support/);assert.equal(u.current(c.id).version,1);assert.equal(u.history(c.id).length,1);
 p.operations[0].prior_evidence=[];raw=JSON.stringify(p);await u.processTurn(next.id);
 assert.ok(sys.includes('上次支持/反证关系不合法'));assert.equal(calls,3);assert.equal(u.current(c.id).version,2);assert.equal(u.history(c.id)[0].evidence[0].id,oldId);assert.equal(u.history(c.id)[1].evidence.length,1);s.close();
});
