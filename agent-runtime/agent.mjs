import { SYSTEM_PROMPT } from './prompt.mjs';
import { randomUUID } from 'node:crypto';
export class Agent {
  constructor(store, gateway){this.store=store;this.gateway=gateway;this.tail=Promise.resolve();}
  reply(input){
    if(typeof input!=='string'||!input.trim()||input.length>16000) return Promise.reject(new Error('Invalid input'));
    const text=input.trim();
    const run=this.tail.then(async()=>{
      const messages=[{role:'system',content:SYSTEM_PROMPT},...this.store.history().flatMap(t=>[{role:'user',content:t.user},{role:'assistant',content:t.assistant}]),{role:'user',content:text}];
      const response=await this.gateway.post('/v1/llm/complete',{request_id:randomUUID(),messages});
      if(typeof response.text!=='string'||!response.text.trim()||response.text.length>64000) throw Error('Invalid model response');
      return this.store.append(text,response.text.trim());
    });
    this.tail=run.catch(()=>{});
    return run;
  }
}
export class Gateway {
  constructor(url, token) {
    const parsed=new URL(url);
    if(parsed.username||parsed.password||parsed.search||parsed.hash||!(parsed.protocol==='https:'||(parsed.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(parsed.hostname)))) throw Error('Gateway requires HTTPS or loopback HTTP');
    if(!token) throw Error('BECOMING_TOKEN required');
    this.url=url.replace(/\/$/,'');this.token=token;
  }
  async post(path,body){
    const res=await fetch(this.url+path,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+this.token},body:JSON.stringify(body),redirect:'error',signal:AbortSignal.timeout(90000)});
    if(!res.ok) throw Error('Gateway HTTP '+res.status);
    return res.json();
  }
}
export class SyncWorker {
  constructor(store,gateway){this.store=store;this.gateway=gateway;this.active=false;this.lastError=null;this.lastSuccess=null;}
  async tick(){
    if(this.active)return;
    this.active=true;
    try {
      const result=await this.gateway.post('/v1/sync/turns',{cursor:this.store.cursor(),turns:this.store.pending()});
      this.store.applySync(result.ack,result.turns,result.cursor);
      this.lastError=null;this.lastSuccess=new Date().toISOString();
    } catch(e){this.lastError='Sync failed; local records retained';}
    finally{this.active=false;}
  }
}
