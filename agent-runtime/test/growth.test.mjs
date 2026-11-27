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

test('model-echoed deletion preview is rebuilt exclusively from DB; confirmation remains required',async()=>{
 const s=new Store(':memory:'),g=new GrowthStore(':memory:');const goal=g.apply(g.prepare('create_goal',{text:'真实目标'})).record;
 const child=g.apply(g.prepare('create_action',{goal_id:goal.id,text:'真实行动'})).record;
 let response='尚未保存。请核对以下变更：\n'+JSON.stringify({tool:'delete_item',args:{id:goal.id},before:{id:999,text:'模型伪造'},parent:{id:999},children:[]});
 const model={complete:async()=>response},a=new Agent(s,model,{growth:new GrowthTools(model,g)});
 const proposal=await a.reply('删除这个目标');assert.equal(proposal.event.growth.status,'proposed');
 assert.equal(proposal.pending_growth.preview.before.id,goal.id);assert.equal(proposal.pending_growth.preview.before.text,'真实目标');assert.deepEqual(proposal.pending_growth.preview.children.map(c=>c.id),[child.id]);assert.equal(g.read('list_goals',{}).items.length,1);
 const committed=await a.reply('/confirm '+proposal.pending_growth.token);assert.equal(committed.event.growth.status,'committed');assert.equal(committed.event.growth.result.deleted_children,1);
 response='尚未保存。请核对以下变更：\n'+JSON.stringify({tool:'create_goal',args:{text:'新目标'},approved:true});assert.equal((await a.reply('创建目标')).event.growth.status,'rejected');
 response='GROWTH_TOOL\n'+JSON.stringify({tool:'create_goal',args:{text:'新目标'},before:{}});assert.equal((await a.reply('创建目标')).event.growth.status,'rejected');
 g.close();s.close();
});

test('natural-language prefix on legacy preview or canonical marker is supported without trusting model snapshots',async()=>{
 const s=new Store(':memory:'),g=new GrowthStore(':memory:');const goal=g.apply(g.prepare('create_goal',{text:'读书'})).record;
 let response='我会为目标“读书”添加行动“读一页”。尚未保存。请核对以下变更：\n'+JSON.stringify({tool:'create_action',args:{goal_id:goal.id,text:'读一页'},parent:{id:999,text:'伪造'}});
 const a=new Agent(s,{complete:async()=>response},{growth:new GrowthTools({complete:async()=>response},g)});
 const first=await a.reply('添加行动');assert.equal(first.event.growth.status,'proposed');assert.equal(first.pending_growth.preview.parent.id,goal.id);assert.equal(g.read('get_goal',{goal_id:goal.id}).items.length,0);
 const committed=await a.reply('/confirm '+first.pending_growth.token);assert.equal(committed.event.growth.status,'committed');
 response='我会按你给出的内容创建成长目标。GROWTH_TOOL\n'+JSON.stringify({tool:'create_goal',args:{text:'新目标'}});
 const next=await a.reply('新建目标');assert.equal(next.event.growth.status,'proposed');assert.equal(g.read('list_goals',{}).items.length,1);
 response='我会创建目标。尚未保存。请核对以下变更：\n'+JSON.stringify({tool:'create_goal',args:{text:'新目标'},approved:true});
 assert.equal((await a.reply('新建目标')).event.growth.status,'rejected');
 response='GROWTH_TOOL\n'+JSON.stringify({tool:'create_goal',args:{text:'新目标'}})+'\n'+JSON.stringify({tool:'delete_item',args:{id:goal.id}});
 assert.equal((await a.reply('新建目标')).event.growth.status,'rejected');assert.equal(g.read('list_goals',{}).items.length,1);
 g.close();s.close();
});

test('legacy snapshot field names are not part of tool contract; history preview is not a model example',async()=>{
 const s=new Store(':memory:'),g=new GrowthStore(':memory:');
 const goal=g.apply(g.prepare('create_goal',{text:'读书'})).record;
 const child=g.apply(g.prepare('create_action',{goal_id:goal.id,text:'读一页'})).record;
 const label='尚未保存。请核对以下变更：\n';
 let context,response=label+JSON.stringify({tool:'update_item',args:{id:child.id,status:'done'},current:{id:999,status:'done'},other_snapshot:[{id:888}],arbitrary_record:{id:777}});
 const model={complete:async m=>{context=m;return response;}},a=new Agent(s,model,{growth:new GrowthTools(model,g)});
 const t=await a.reply('完成行动');assert.equal(t.event.growth.status,'proposed');
 assert.equal(t.pending_growth.preview.before.id,child.id);assert.equal(t.pending_growth.preview.before.status,'pending');
 assert.equal(g.item(child.id).status,'pending');await a.reply('/confirm '+t.pending_growth.token);assert.equal(g.item(child.id).status,'done');
 response=label+JSON.stringify({tool:'delete_item',args:{id:child.id},approval:{confirmed:true}});
 assert.equal((await a.reply('删除行动')).event.growth.status,'rejected');assert.ok(g.item(child.id));
 assert.ok(context.some(m=>m.role==='assistant'&&m.content.startsWith('已向用户展示本地变更预览')));
 assert.ok(context.some(m=>m.role==='assistant'&&m.content.startsWith('已保存变更：')));
 assert.ok(s.history().some(t=>t.assistant.startsWith(label)));
 response=label+JSON.stringify({tool:'update_item',args:{id:child.id,status:'completed'},record:{status:'done'}});
 assert.equal((await a.reply('更新行动')).event.growth.status,'rejected');assert.equal(g.item(child.id).status,'done');
 g.close();s.close();
});
