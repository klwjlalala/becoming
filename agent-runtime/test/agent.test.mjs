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
test('structured prompts persist as conversation instructions beyond the history window',async()=>{
 const store=new Store(':memory:'),calls=[];
 const model={complete:async messages=>{calls.push(messages);return '收到';}};
 const agent=new Agent(store,model,{historyTurns:2});
 const prompt='Role：研究顾问\\n严格遵守以下要求。\\n提问流程\\n最终交付一份完整报告。\\n'+('根据用户回答逐步调整任务，不要提前总结。'.repeat(50));
 const first=await agent.reply(prompt);
 assert.ok(first.event.session_instruction);
 assert.equal(first.event.session_instruction.status,'pinned');
 assert.equal(store.getInstructions().content,prompt);
 assert.equal(store.getInstructions().source_turn_id,first.id);
 assert.ok(calls[0][0].content.includes(prompt));
 assert.equal(calls[0].at(-1).content,'请开始执行本次会话指令。');
 for(let i=0;i<5;i++)await agent.reply('第'+i+'轮用户补充');
 const last=calls.at(-1);
 assert.ok(last[0].content.includes(prompt),'Pinned instruction disappeared after the recent-history window rolled over');
 assert.ok(!last.some(message=>message.content===prompt),'Original prompt was duplicated in transcript history');
 assert.equal(store.history(2).length,2);

 const replacement='Role：新的研究任务\\n目标：比较三个可行方案。\\n严格遵守边界并输出结构化结论。';
 await agent.reply('/set-instructions\\n'+replacement);
 assert.equal(store.getInstructions().version,2);
 assert.ok(calls.at(-1)[0].content.includes(replacement));
 assert.ok(!calls.at(-1)[0].content.includes(prompt));

 const callCount=calls.length;
 const cleared=await agent.reply('/clear-instructions');
 assert.equal(cleared.event.session_instruction.status,'cleared');
 assert.equal(store.getInstructions(),null);
 assert.equal(calls.length,callCount,'Clearing instructions should not consume a model call');
 const after=await agent.reply('继续普通聊天');
 assert.equal(after.event.session_instruction,null);
 assert.ok(!calls.at(-1)[0].content.includes(replacement));
 store.close();
});
test('long reference text is not promoted to session instructions without a role header',async()=>{
 const store=new Store(':memory:'),calls=[];
 const agent=new Agent(store,{complete:async messages=>{calls.push(messages);return '已收到资料';}});
 const reference='这是一份需要分析的普通资料。'.repeat(100);
 const turn=await agent.reply(reference);
 assert.equal(store.getInstructions(),null);
 assert.equal(calls[0].at(-1).content,reference);
 assert.equal(turn.event.session_instruction,null);
 store.close();
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
