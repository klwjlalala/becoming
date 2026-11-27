import test from 'node:test';
import assert from 'node:assert/strict';
import {Store} from '../store.mjs';
import {Agent} from '../agent.mjs';
import {GrowthStore,GrowthTools} from '../growth.mjs';
const call=(tool,args)=>'GROWTH_TOOL\n'+JSON.stringify({tool,args});
test('actual agent tool lifecycle, user confirmation, one-shot and read result',async()=>{
 const store=new Store(':memory:'),g=new GrowthStore(':memory:');let response=call('create_goal',{text:'练习阅读'}),last;
 const model={complete:async m=>{last=m;return m.at(-1).content.includes('本地工具真实结果')?'已读取目标':response;}};
 const tools=new GrowthTools(model,g),agent=new Agent(store,model,{growth:tools});
 const t=await agent.reply('帮我记录成长目标');assert.equal(t.event.growth.status,'proposed');assert.equal(g.read('list_goals',{}).items.length,0);
 const token=t.pending_growth.token;assert.ok(!store.history()[0].assistant.includes(token));
 assert.equal((await agent.reply('/confirm wrong')).event.growth.status,'invalid_confirmation');
 const done=await agent.reply('/confirm '+token);assert.equal(done.event.growth.status,'committed');
 assert.equal((await agent.reply('/confirm '+token)).event.growth.status,'invalid_confirmation');assert.equal(g.read('list_goals',{}).items.length,1);
 response=call('list_goals',{});const read=await agent.reply('查看目标');assert.equal(read.event.growth.status,'read');assert.ok(last.at(-1).content.includes('练习阅读'));assert.equal(read.assistant,'已读取目标');
 g.close();store.close();
});
test('all mutation tools and stale previews, cascade deletion, invalid arguments',()=>{
 const g=new GrowthStore(':memory:');
 const goal=g.apply(g.prepare('create_goal',{text:'g'})).record;
 const action=g.apply(g.prepare('create_action',{goal_id:goal.id,text:'a'})).record;
 const reflection=g.apply(g.prepare('record_reflection',{goal_id:goal.id,text:'r'})).record;
 const stale=g.prepare('delete_item',{id:goal.id});g.apply(g.prepare('update_item',{id:action.id,status:'done'}));
 assert.throws(()=>g.apply(stale));assert.throws(()=>g.prepare('update_item',{id:reflection.id,status:'done'}));assert.throws(()=>g.prepare('create_action',{goal_id:action.id,text:'a'}));
 assert.equal(g.read('get_goal',{goal_id:goal.id}).items.length,2);
 assert.equal(g.apply(g.prepare('delete_item',{id:goal.id})).deleted_children,2);assert.equal(g.read('list_goals',{}).items.length,0);g.close();
});
test('conversation history and growth confirmation do not cross sessions',async()=>{
 const store=new Store(':memory:'),g=new GrowthStore(':memory:'),other=store.createConversation('other').id;let last;
 const model={complete:async m=>{last=m;return call('create_goal',{text:'goal'});}};
 const tools=new GrowthTools(model,g),agent=new Agent(store,model,{growth:tools});
 const first=await agent.reply('private session text');await agent.reply('second',other);
 assert.ok(!last.some(m=>m.content==='private session text'));
 assert.equal((await agent.reply('/confirm '+first.pending_growth.token,other)).event.growth.status,'invalid_confirmation');
 assert.equal((await agent.reply('/confirm '+first.pending_growth.token)).event.growth.status,'committed');
 assert.equal(g.read('list_goals',{}).items.length,1);g.close();store.close();
});
