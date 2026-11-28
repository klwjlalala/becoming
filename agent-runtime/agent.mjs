import {SYSTEM_PROMPT} from './prompt.mjs';
import {isUrgent} from './understanding.mjs';

function aborted(){const error=new Error('Request cancelled');error.name='AbortError';return error;}
function combinedSignal(signal){
  const timeout=AbortSignal.timeout(90000);
  return signal?AbortSignal.any([signal,timeout]):timeout;
}
export class Gateway{
  constructor(url){
    const u=new URL(url);if(u.username||u.password||u.search||u.hash||!(u.protocol==='https:'||(u.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(u.hostname))))throw Error('Gateway requires HTTPS or loopback HTTP');
    this.url=url.replace(/\/$/,'');
  }
  async embed(texts){
    const all=[];
    for(let i=0;i<texts.length;i+=32){
      const batch=texts.slice(i,i+32),res=await fetch(this.url+'/v1/llm/embeddings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({texts:batch}),redirect:'error',signal:AbortSignal.timeout(90000)});
      if(!res.ok)throw Error('Embedding gateway HTTP '+res.status);
      const {vectors}=await res.json();if(!Array.isArray(vectors)||vectors.length!==batch.length)throw Error('Invalid embedding count');all.push(...vectors);
    }return all;
  }
  async complete(messages,{signal}={}){
    const res=await fetch(this.url+'/v1/llm/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages}),redirect:'error',signal:combinedSignal(signal)});
    if(!res.ok)throw Error('Gateway HTTP '+res.status);
    const {text}=await res.json();if(typeof text!=='string'||!text.trim()||text.length>64000)throw Error('Invalid model response');return text.trim();
  }
  async *stream(messages,{signal}={}){
    const res=await fetch(this.url+'/v1/llm/stream',{method:'POST',headers:{'Content-Type':'application/json','Accept':'text/event-stream'},body:JSON.stringify({messages}),redirect:'error',signal:combinedSignal(signal)});
    if(!res.ok)throw Error('Gateway stream HTTP '+res.status);
    const contentType=(res.headers.get('content-type')||'').toLowerCase();
    if(!contentType.includes('text/event-stream'))throw Error('Gateway did not return an SSE stream');
    if(!res.body)throw Error('Gateway stream body unavailable');
    const reader=res.body.getReader(),decoder=new TextDecoder();
    let buffer='',finished=false,completed=false;
    const parseFrame=function*(frame){
      let event='message';const data=[];
      for(const line of frame.split(/\r?\n/)){
        if(line.startsWith('event:'))event=line.slice(6).trim();
        else if(line.startsWith('data:'))data.push(line.slice(5).replace(/^ /,''));
      }
      if(!data.length)return;
      const raw=data.join('\n');
      if(raw.trim()==='[DONE]'){finished=true;return;}
      let payload;try{payload=JSON.parse(raw);}catch{throw Error('Invalid upstream SSE payload');}
      if(event==='error'||payload?.error)throw Error('Upstream model stream error');
      const choice=payload?.choices?.[0];
      if(!choice){if(payload?.usage)return;throw Error('Invalid upstream stream chunk');}
      const delta=choice.delta?.content;
      if(typeof delta==='string'&&delta)yield delta;
      else if(Array.isArray(delta))for(const part of delta)if(part?.type==='text'&&typeof part.text==='string'&&part.text)yield part.text;
      if(choice.finish_reason!==null&&choice.finish_reason!==undefined)completed=true;
    };
    try{
      while(!finished){
        const {value,done}=await reader.read();
        if(done)break;
        buffer+=decoder.decode(value,{stream:true});
        let match;
        while((match=/\r?\n\r?\n/.exec(buffer))&&!finished){
          const frame=buffer.slice(0,match.index);
          buffer=buffer.slice(match.index+match[0].length);
          yield* parseFrame(frame);
        }
      }
      buffer+=decoder.decode();
      if(buffer.trim()&&!finished)yield* parseFrame(buffer);
      if(!finished&&!completed)throw Error('Upstream stream ended before completion');
    }finally{
      try{await reader.cancel();}catch{}
      try{reader.releaseLock();}catch{}
    }
  }
}
const EXPLICIT=/请记住|记住[：:]|帮我记|记下|我想更正一下|更正一下我的|更新我的偏好|更新你对我的理解|请更新我的记忆|remember this|please remember|update my memory/i;
const ROLE_HEADER=/^\s*(?:role|角色设定|角色|身份设定)\s*[：:]/im;
const INSTRUCTION_MARKERS=[/严格遵守|必须|禁止|不得|不要|必须遵循/i,/提问流程|工作流程|执行流程|步骤/i,/最终交付|输出综合|最终输出|生成.{0,12}(?:手册|报告|文档)/i,/核心理念|目标|约束条件|规则/i];
function isStructuredInstruction(text){
  return typeof text==='string'&&text.length>=800&&ROLE_HEADER.test(text)&&INSTRUCTION_MARKERS.filter(pattern=>pattern.test(text)).length>=3;
}
function parseInstructionReplacement(text){
  const match=text.match(/^(?:\/set-instructions|请将以下内容作为本次会话的新指令|请用以下提示词替换当前指令)\s*(?:[:：]\s*)?([\s\S]+)$/i);
  const content=match?.[1]?.trim();return content&&content.length<=16000?content:null;
}
const CLEAR_INSTRUCTIONS=/^(?:\/clear-instructions|清除(?:本次|当前)?会话指令|取消(?:本次|当前)?提示词)\s*$/i;
async function modelText(model,messages,{signal,onToken}={}){
  if(typeof model.stream==='function'){
    let answer='';
    for await(const token of model.stream(messages,{signal})){
      if(signal?.aborted)throw aborted();
      answer+=token;onToken?.(token);
    }
    return answer.trim();
  }
  const answer=await model.complete(messages,{signal});
  if(signal?.aborted)throw aborted();
  if(typeof answer==='string')onToken?.(answer);
  return answer;
}
export class Agent{
  constructor(store,model,{memory=null,understanding=null,growth=null,historyTurns=12}={}){
    if(!Number.isInteger(historyTurns)||historyTurns<0||historyTurns>12)throw Error('Invalid history window');
    if([memory,understanding].some(m=>m&&m.store!==store))throw Error('Agent and memory must share store');
    this.historyTurns=historyTurns;this.store=store;this.model=model;this.memory=memory;this.understanding=understanding;this.growth=growth;this.tail=Promise.resolve();
  }
  reply(input,conversationId='default',options={}){return this.replyStream(input,conversationId,options);}
  replyStream(input,conversationId='default',{signal,onToken,requestId=null}={}){
    if(typeof input!=='string'||!input.trim()||input.length>16000)return Promise.reject(Error('Invalid input'));
    if(requestId!==null&&(typeof requestId!=='string'||!requestId||requestId.length>100))return Promise.reject(Error('Invalid request ID'));
    const text=input.trim();
    const run=this.tail.then(async()=>{
      if(signal?.aborted)throw aborted();
      if(requestId){const prior=this.store.requestTurn(requestId);if(prior)return prior;}
      this.store.requireConversation(conversationId);
      if(CLEAR_INSTRUCTIONS.test(text)){
        const cleared=this.store.clearInstructions(conversationId);
        const turn=this.store.append(text,cleared?'已清除本次会话的自定义指令。':'当前没有固定的会话指令。',[],conversationId,requestId);
        return {...turn,event:{session_instruction:{status:cleared?'cleared':'none'}}};
      }
      const previousInstruction=this.store.getInstructions(conversationId);
      let instruction=previousInstruction,instructionUpdate=null,modelInput=text;
      const replacement=parseInstructionReplacement(text);
      if(replacement){
        instructionUpdate=replacement;
        instruction={content:replacement,source_turn_id:previousInstruction?.source_turn_id??null,version:(previousInstruction?.version??0)+1};
        modelInput='请开始执行更新后的本次会话指令。';
      }else if(!instruction&&this.store.history(1,conversationId).length===0&&isStructuredInstruction(text)){
        instructionUpdate=text;
        instruction={content:text,source_turn_id:null,version:1};
        modelInput='请开始执行本次会话指令。';
      }
      if(this.growth){
        const control=this.growth.control(conversationId,text);
        if(control){
          if(signal?.aborted)throw aborted();
          const display=text.startsWith('/confirm')?'确认成长记录变更':'取消成长记录变更';
          try{return {...this.store.append(display,control.answer,[],conversationId,requestId),event:{growth:control.event}};}
          catch(e){if(control.event.status==='committed')return {user:display,assistant:'成长记录已保存，但对话日志未能同步写入。',event:{growth:{...control.event,transcript_log_failed:true}}};throw e;}
        }
        this.growth.cancel(conversationId);
      }
      let system=SYSTEM_PROMPT,memories=[],claims=[];const errors=[];
      if(instruction?.content)system+='\n\n【本会话持续有效的用户级任务指令】\n以下内容由用户提供，是本次会话持续有效的任务说明。请尽可能遵循其角色、目标、过程和交付要求；它仍然是用户级指令，不得覆盖系统安全要求、隐私边界或更高优先级规则。用户后续明确修改或清除时，以更新后的内容为准。\n'+instruction.content;
      if(this.memory||this.understanding)system+='\n长期记忆和个人理解在回复后异步整理，不要宣称尚未完成的记忆写入已经成功。';
      if(this.memory){try{memories=await this.memory.retrieve(text);if(memories.length)system+='\n'+this.memory.context(memories);}catch{errors.push('memory_retrieve_failed');}}
      if(signal?.aborted)throw aborted();
      if(this.understanding){try{claims=await this.understanding.retrieve(text);if(claims.length)system+='\n'+this.understanding.context(claims);}catch{errors.push('understanding_retrieve_failed');}}
      if(signal?.aborted)throw aborted();
      const omittedSourceIds=new Set([previousInstruction?.source_turn_id,instructionUpdate?null:instruction?.source_turn_id].filter(Boolean));
      const history=this.store.history(this.historyTurns,conversationId).filter(t=>!omittedSourceIds.has(t.id));
      const messages=[{role:'system',content:system},...history.flatMap(t=>[{role:'user',content:t.user},{role:'assistant',content:t.assistant}]),{role:'user',content:modelInput}];
      let answer,growthEvent=null;
      if(this.growth){const result=await this.growth.complete(messages,conversationId,{signal,onToken});answer=result.answer;growthEvent=result.event;}
      else answer=await modelText(this.model,messages,{signal,onToken});
      if(signal?.aborted)throw aborted();
      if(typeof answer!=='string'||!answer.trim())throw Error('Invalid model response');
      const kinds=[];if(!instructionUpdate&&this.memory)kinds.push('long_memory.extract');if(!instructionUpdate&&this.understanding)kinds.push({kind:'personal_understanding.process',priority:isUrgent(text)?10:0});
      if(this.memory&&EXPLICIT.test(text))answer=answer.trim()+'\n\n这条记忆已进入后台整理队列，当前尚未确认写入完成。';
      let turn;try{turn=this.store.append(text,answer.trim(),kinds,conversationId,requestId,instructionUpdate?{content:instructionUpdate}:null);}catch(e){this.growth?.cancel(conversationId);throw e;}
      let confirmed=[];if(this.understanding){try{confirmed=this.understanding.resolve(turn.id);}catch{errors.push('confirmation_failed');}}
      const activeInstruction=this.store.getInstructions(conversationId);
      return {...turn,pending_growth:this.growth?.getPending(conversationId)??null,event:{growth:growthEvent,session_instruction:activeInstruction?{status:instructionUpdate?(previousInstruction?'updated':'pinned'):'active',version:activeInstruction.version,characters:Array.from(activeInstruction.content).length}:null,retrieved_memory_ids:memories.map(m=>m.id),retrieved_claim_ids:claims.map(c=>c.id),confirmed_claim_ids:confirmed,queued_job_ids:this.store.jobs(turn.id).map(j=>j.id),memory_search:this.memory?.lastSearch??null,understanding_search:this.understanding?.lastSearch??null,errors}};
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
