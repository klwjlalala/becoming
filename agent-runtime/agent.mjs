import {SYSTEM_PROMPT} from './prompt.mjs';
export class Gateway{
  constructor(url){
    const u=new URL(url);if(u.username||u.password||u.search||u.hash||!(u.protocol==='https:'||(u.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(u.hostname))))throw Error('Gateway requires HTTPS or loopback HTTP');
    this.url=url.replace(/\/$/,'');
  }
  async complete(messages){
    const res=await fetch(this.url+'/v1/llm/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages}),redirect:'error',signal:AbortSignal.timeout(90000)});
    if(!res.ok)throw Error('Gateway HTTP '+res.status);
    const {text}=await res.json();if(typeof text!=='string'||!text.trim()||text.length>64000)throw Error('Invalid model response');return text.trim();
  }
}
const EXPLICIT=/请记住|记住[：:]|帮我记|记下|我想更正一下|更正一下我的|更新我的偏好|更新你对我的理解|请更新我的记忆|remember this|please remember|update my memory/i;
export class Agent{
  constructor(store,model,{memory=null,understanding=null,growth=null}={}){this.store=store;this.model=model;this.memory=memory;this.understanding=understanding;this.growth=growth;this.tail=Promise.resolve();}
  reply(input,conversationId='default'){
    if(typeof input!=='string'||!input.trim()||input.length>16000)return Promise.reject(Error('Invalid input'));
    const text=input.trim();
    const run=this.tail.then(async()=>{
      this.store.requireConversation(conversationId);
      if(this.growth){
        const control=this.growth.control(conversationId,text);
        if(control){
          // Never persist the nonce in transcript or memory inputs.
          const display=text.startsWith('/confirm')?'确认成长记录变更':'取消成长记录变更';
          try{return {...this.store.append(display,control.answer,[],conversationId),event:{growth:control.event}};}
          catch(e){if(control.event.status==='committed')return {user:display,assistant:'成长记录已保存，但对话日志未能同步写入。',event:{growth:{...control.event,transcript_log_failed:true}}};throw e;}
        }
        this.growth.cancel(conversationId);
      }
      let system=SYSTEM_PROMPT,memories=[],claims=[];const errors=[];
      if(this.memory||this.understanding)system+='\n长期记忆和个人理解在回复后异步整理，不要宣称尚未完成的记忆写入已经成功。';
      if(this.memory){try{memories=await this.memory.retrieve(text);if(memories.length)system+='\n'+this.memory.context(memories);}catch{errors.push('memory_retrieve_failed');}}
      if(this.understanding){try{claims=await this.understanding.retrieve(text);if(claims.length)system+='\n'+this.understanding.context(claims);}catch{errors.push('understanding_retrieve_failed');}}
      const messages=[{role:'system',content:system},...this.store.history(12,conversationId).flatMap(t=>[{role:'user',content:t.user},{role:'assistant',content:t.assistant}]),{role:'user',content:text}];
      let answer, growthEvent=null;
      if(this.growth){const result=await this.growth.complete(messages,conversationId);answer=result.answer;growthEvent=result.event;}else answer=await this.model.complete(messages);
      if(typeof answer!=='string'||!answer.trim())throw Error('Invalid model response');
      const kinds=[];if(this.memory)kinds.push('long_memory.extract');if(this.understanding)kinds.push('personal_understanding.process');
      if(this.memory&&EXPLICIT.test(text))answer=answer.trim()+'\n\n这条记忆已进入后台整理队列，当前尚未确认写入完成。';
      let turn;try{turn=this.store.append(text,answer.trim(),kinds,conversationId);}catch(e){this.growth?.cancel(conversationId);throw e;}
      let confirmed=[];if(this.understanding){try{confirmed=this.understanding.resolve(turn.id);}catch{errors.push('confirmation_failed');}}
      return {...turn,pending_growth:this.growth?.getPending(conversationId)??null,event:{growth:growthEvent,retrieved_memory_ids:memories.map(m=>m.id),retrieved_claim_ids:claims.map(c=>c.id),confirmed_claim_ids:confirmed,queued_job_ids:this.store.jobs(turn.id).map(j=>j.id),errors}};
    });
    this.tail=run.catch(()=>{});return run;
  }
}
export class BackgroundWorker{
  constructor(store,handlers){this.store=store;this.handlers=handlers;this.active=false;}
  async tick(){
    if(this.active)return false;this.active=true;
    try{const job=this.store.claim();if(!job)return false;
      try{const handler=this.handlers[job.kind];if(!handler)throw Error('Unsupported job');await handler(job.turn_id);this.store.finish(job.id);}
      catch{this.store.finish(job.id,'Processing failed');}
      return true;
    }finally{this.active=false;}
  }
}
