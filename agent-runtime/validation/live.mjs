import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {mkdirSync,writeFileSync} from 'node:fs';
import {dirname} from 'node:path';
import {BudgetedModel,runtime} from './runtime.mjs';
const model=new BudgetedModel(36),report={fictional_data_only:true,cases:[],model_calls:0};
const out=process.env.BECOMING_REPORT||'artifacts/node-live-functional.json';
async function scenario(name,options,run){const rt=runtime(model,options),item={name,status:'failed'};report.cases.push(item);try{await run(rt,item);item.status='passed';}catch(e){item.error=e.message;process.exitCode=1;}finally{rt.close();console.log(name+': '+item.status+(item.error?' — '+item.error:''));}}
await scenario('explicit memory extract, recall, revision and forget',{memory:true,semantic:true},async(r,item)=>{
 const marker='BE-'+randomUUID().slice(0,8),next=marker+'-NEW';
 await r.reply('请将这条虚构信息保存为长期事实记忆，key 使用 test_code：我的测试代号是 '+marker+'。');
 const old=r.m.list().find(m=>m.quote.includes(marker));assert.ok(old,'Memory not persisted');
 const recall=await r.reply('请检索长期记忆，我的测试代号是什么？只回复代号。');
 assert.ok(recall.assistant.includes(marker));assert.ok(recall.event.retrieved_memory_ids.includes(old.id));
 await r.reply('请更新长期记忆槽位 '+old.key+'，替换旧代号：我的测试代号是 '+next+'。');
 const updated=r.m.list().find(m=>m.key===old.key);assert.ok(updated?.quote.includes(next));assert.notEqual(updated.id,old.id);
 assert.ok(r.m.forget(old.key)>=2);assert.ok(!r.m.list().some(m=>m.key===old.key));
 item.records={old,updated,recall:recall.event};
});
await scenario('all seven existing growth tools',{growth:true,historyTurns:12},async(r,item)=>{
 const events=[];item.events=events;
 async function mutate(tool,prompt){const t=await r.reply(prompt);events.push(t.event.growth);assert.equal(t.event.growth?.tool,tool);assert.equal(t.event.growth?.status,'proposed');assert.ok(t.pending_growth);const done=await r.reply('/confirm '+t.pending_growth.token);assert.equal(done.event.growth?.status,'committed');events.push(done.event.growth);return done.event.growth.result;}
 const goal=(await mutate('create_goal','明确调用 create_goal，text 为虚构目标：读书。')).record;
 const action=(await mutate('create_action','明确调用 create_action，goal_id='+goal.id+'，text=读一页。')).record;
 const reflection=(await mutate('record_reflection','明确调用 record_reflection，goal_id='+goal.id+'，text=感觉平静。')).record;
 const updated=await mutate('update_item','明确调用 update_item，id='+action.id+'，status=done。');assert.equal(updated.record.status,'done');
 for(const [tool,prompt] of [['list_goals','明确调用 list_goals 列出目标。'],['get_goal','明确调用 get_goal，goal_id='+goal.id+'。']]){const t=await r.reply(prompt);events.push(t.event.growth);assert.equal(t.event.growth?.tool,tool);assert.equal(t.event.growth?.status,'read');assert.ok(!t.event.growth?.followup_failed);}
 await mutate('delete_item','明确调用 delete_item，id='+reflection.id+'。');assert.equal(r.g.read('get_goal',{goal_id:goal.id}).items.length,1);
});
await scenario('explicit understanding formation and correction',{understanding:true},async(r,item)=>{
 await r.reply('请更新你对我的理解：我目前把创业视为自己最重要的人生目标。这是虚构测试设定。');
 const first=r.u.list();assert.ok(first.length,'No claims created');
 await r.reply('更正一下：创业并不是我的人生目标；我真正希望的是有选择权，创业只是一个可选方式。这仍然只是虚构测试设定。');
 item.histories=first.map(c=>r.u.history(c.id));assert.ok(item.histories.some(h=>h.length>=2),'Existing claim was not revised');
 const answer=await r.reply('结合之前聊过的内容，我真正想要什么样的生活？');item.answer=answer;assert.ok(answer.event.retrieved_claim_ids.length);
 for(const c of r.u.list()){const current=r.u.history(c.id).find(v=>v.version===c.version);assert.ok(current.evidence.length);for(const e of current.evidence)assert.ok(r.store.turn(e.source_turn_id).user.includes(e.quote));}
});
report.model_calls=model.calls;report.max_calls=model.limit;report.call_durations_ms=model.timings;
mkdirSync(dirname(out),{recursive:true});writeFileSync(out,JSON.stringify(report,null,2)+'\n');console.log('Model calls:',model.calls,'/',model.limit);
