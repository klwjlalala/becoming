import {EXTRACT_PROMPT,SELECT_PROMPT,MEMORY_CONTEXT} from './memory-prompts.mjs';
import {LISTEN_ONLY_CUES,THIRD_PARTY_ONLY_CUES,TRANSIENT_MOOD_CUES,PERSONAL_QUERY_CUES} from './understanding-policy.mjs';
export const SECRET=/(?:\bsk-[a-z0-9_-]{12,}|(?:api[_ -]?key|password|密码|密钥)\s*[:：=]\s*\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----)/i;
const KEY=/^[\p{L}\p{N}_-]{1,48}$/u;
const CATEGORIES=new Set(['fact','experience','subjective']);
const STOP=new Set(['我的','我想','我是','什么','之前','一下','这个','那个','请问','可以','remember','what','the','my','about']);
const BOUNDARY=new Set('，,。.!！？?；;：:\n\r'), HARD=new Set('。.!！？?；;\n\r');
const PREFIX=/(?:如果|假如|假设|假定|除非|只有|只要|前提|倘若|朋友说|同事说|他说|她说|别人说|引用|例如|比方说|if\b|unless\b|suppose\b|assuming\b|said\b)/i;
const SUFFIX=/^(?:但|不过|然而|只是|而不是|不是|除非|才|仅限|前提|并非|but\b|however\b|unless\b|only\b)/i;
const CUES={fact:['职业','工作','身份','代号','信息'],experience:['经历','过去','以前','发生'],subjective:['喜欢','偏好','价值观','兴趣','目标']};
export function completeQuote(quote,source){
  if(typeof quote!=='string'||!quote.trim()||!source.includes(quote))return false;
  for(let start=source.indexOf(quote);start!==-1;start=source.indexOf(quote,start+1)){
    const end=start+quote.length,left=source.slice(0,start).trimEnd(),right=source.slice(end).trimStart();
    if(left&&!BOUNDARY.has(left.at(-1))&&!BOUNDARY.has(quote[0]))return false;
    if(right&&!BOUNDARY.has(right[0])&&!BOUNDARY.has(quote.at(-1)))return false;
    const before=source.slice(0,start).split(/[。.!！？?；;\n\r]/).at(-1),after=source.slice(end).split(/[。.!！？?；;\n\r]/)[0];
    if(!HARD.has(quote[0])&&PREFIX.test(before))return false;
    if(!HARD.has(quote.at(-1))&&SUFFIX.test(after.replace(/^[，,：: \t]+/,'')))return false;
  }return true;
}
export function terms(text){
  const result=new Set(text.toLowerCase().match(/[a-z0-9_]+/g)||[]);
  for(const run of text.match(/[\u3400-\u9fff]+/g)||[])for(let i=0;i<run.length-1;i++)result.add(run.slice(i,i+2));
  for(const t of STOP)result.delete(t);return result;
}
const overlap=(a,b)=>[...a].filter(x=>b.has(x)).length;
const has=(text,cues)=>cues.some(cue=>text.includes(cue));
function retrievalSuppression(query){
  const reflective=has(query,PERSONAL_QUERY_CUES);
  return has(query,LISTEN_ONLY_CUES)?'listen_only':has(query,THIRD_PARTY_ONLY_CUES)&&!has(query,['我自己','我也','我为什么','我感到','让我','对我来说'])?'third_party_only':has(query,TRANSIENT_MOOD_CUES)&&!reflective?'transient_mood':null;
}
function normalize(key){if(typeof key!=='string'||!KEY.test(key=key.trim().toLowerCase()))throw Error('Invalid memory key');return key;}
export function parseCandidate(item,user){
  if(!item||typeof item!=='object'||Array.isArray(item)||!['category,key,quote','category,key,quote,replaces'].includes(Object.keys(item).sort().join(',')))throw Error('Invalid memory item');
  const {category,quote,replaces=null}=item;
  if(typeof item.key!=='string'||typeof quote!=='string'||!CATEGORIES.has(category))throw Error('Invalid memory fields');
  const key=item.key.toLowerCase();
  if(!KEY.test(key)||quote.length>600||!completeQuote(quote,user)||SECRET.test(quote)||SECRET.test(key)|| (replaces!==null&&(!Number.isSafeInteger(replaces)||replaces<1)))throw Error('Invalid memory source or revision');
  return {key,category,quote,replaces};
}
export class LongMemory{
  constructor(store,model,{semantic=false}={}){this.store=store;this.db=store.db;this.model=model;this.semantic=semantic;this.lastSearch=null;}
  blockedKeys(){return this.db.prepare('SELECT key FROM blocked_memory_keys ORDER BY key').all().map(r=>r.key);}
  allow(key){return this.db.prepare('DELETE FROM blocked_memory_keys WHERE key=?').run(normalize(key)).changes>0;}
  forget(key){key=normalize(key);return this.store.transaction(()=>{this.db.prepare('INSERT OR IGNORE INTO blocked_memory_keys VALUES(?)').run(key);return this.db.prepare('DELETE FROM long_memories WHERE key=?').run(key).changes;});}
  list(active=true){
    return this.db.prepare('SELECT m.*,t.created_at AS recorded_at,t.user AS source FROM long_memories m JOIN turns t ON t.id=m.source_turn_id'+(active?' WHERE m.active=1':'')+' ORDER BY m.id DESC').all().filter(m=>!SECRET.test(m.source)&&completeQuote(m.quote,m.source)).map(({source,...m})=>m);
  }
  async retrieve(query,limit=5){
    this.lastSearch=null;
    if(!Number.isInteger(limit)||limit<0||limit>10)throw Error('Invalid limit');
    if(!limit||!query.trim()||SECRET.test(query)){
      this.lastSearch={candidate_ids:[],selected_ids:[],query_mode:'empty'};
      return [];
    }
    const suppression=retrievalSuppression(query);
    if(suppression){
      this.lastSearch={candidate_ids:[],selected_ids:[],query_mode:'suppressed',suppression_reason:suppression};
      return [];
    }
    const q=terms(query),ranked=this.list().map(m=>{let score=3*overlap(q,terms(m.key))+overlap(q,terms(m.quote));if(score&&CUES[m.category].some(c=>query.includes(c)))score++;return {m,score};}).sort((a,b)=>b.score-a.score||b.m.id-a.m.id);
    if(!this.semantic){
      const candidates=ranked.filter(r=>r.score>0),selected=candidates.slice(0,limit).map(r=>r.m);
      this.lastSearch={candidate_ids:candidates.map(r=>r.m.id),selected_ids:selected.map(m=>m.id),query_mode:'lexical'};
      return selected;
    }
    const pool=ranked.slice(0,40).map(r=>r.m);
    if(!pool.length){this.lastSearch={candidate_ids:[],selected_ids:[],query_mode:'semantic'};return [];}
    const raw=await this.model.complete([{role:'system',content:SELECT_PROMPT},{role:'user',content:JSON.stringify({query,limit,candidates:pool.map(({id,key,category,quote})=>({id,key,category,quote}))})}]);
    const ids=JSON.parse(raw),known=new Map(pool.map(m=>[m.id,m]));
    if(!Array.isArray(ids)||ids.length>limit||new Set(ids).size!==ids.length||ids.some(id=>!Number.isInteger(id)||!known.has(id)))throw Error('Invalid selected ID');
    this.lastSearch={candidate_ids:pool.map(m=>m.id),selected_ids:ids,query_mode:'semantic'};
    return ids.map(id=>known.get(id));
  }
  context(items){return MEMORY_CONTEXT+'\n'+JSON.stringify(items.map(({recorded_at,active,...m})=>({...m,recorded_at_utc:recorded_at,active:!!active})));}
  receipt(id){return this.db.prepare('SELECT 1 FROM long_memory_extraction_receipts WHERE turn_id=?').get(id);}
  mark(id){this.db.prepare('INSERT OR IGNORE INTO long_memory_extraction_receipts VALUES(?)').run(id);}
  writeChecked(c,turnId){
    const {key,category,quote,replaces}=c;
    if(this.db.prepare('SELECT 1 FROM blocked_memory_keys WHERE key=?').get(key))return null;
    const old=this.db.prepare('SELECT id,category,quote FROM long_memories WHERE key=? AND active=1').get(key);
    if(old&&old.category===category&&old.quote===quote)return null;
    if((old&&(replaces!==old.id||category!==old.category))||(!old&&replaces!==null))throw Error('Memory revision conflict');
    if(this.db.prepare('SELECT 1 FROM long_memories WHERE category=? AND quote=? AND active=1').get(category,quote))return null;
    this.db.prepare('UPDATE long_memories SET active=0 WHERE key=? AND active=1').run(key);
    return Number(this.db.prepare('INSERT INTO long_memories(key,category,quote,source_turn_id) VALUES(?,?,?,?)').run(key,category,quote,turnId).lastInsertRowid);
  }
  write(turnId,candidates){
    const turn=this.store.turn(turnId);if(!turn||!Array.isArray(candidates)||candidates.length>12)throw Error('Invalid memory source or batch');
    if(SECRET.test(turn.user))return [];
    const checked=candidates.map(c=>parseCandidate(c,turn.user));
    if(new Set(checked.map(c=>c.key)).size!==checked.length)throw Error('Duplicate keys');
    return this.store.transaction(()=>checked.map(c=>this.writeChecked(c,turnId)).filter(id=>id!==null));
  }
  extractionPrompt(){return EXTRACT_PROMPT;}
  validateRevision(_candidate){}
  async extract(turnId){
    if(this.receipt(turnId))return {written:[],rejected:0};
    const turn=this.store.turn(turnId);if(!turn)throw Error('Missing source');
    const user=turn.user;
    if(user.length>8000||SECRET.test(user)){this.mark(turnId);return {written:[],rejected:0};}
    const q=terms(user),score=m=>overlap(q,new Set([...terms(m.key),...terms(m.quote)]));
    const hints=this.list().sort((a,b)=>score(b)-score(a)||b.id-a.id).slice(0,30).map(({id,key,category,quote})=>({id,key,category,quote}));
    const raw=await this.model.complete([{role:'system',content:this.extractionPrompt()},{role:'user',content:JSON.stringify({current_user_message:user,existing_slots:hints,blocked_keys:this.blockedKeys().slice(0,100)})}]);
    const data=JSON.parse(raw);if(!Array.isArray(data)||data.length>12)throw Error('Invalid extraction batch');
    const parsed=[];let rejected=0,conflicts=0;
    for(const item of data){try{parsed.push(parseCandidate(item,user));}catch{rejected++;}}
    const counts=new Map();for(const c of parsed)counts.set(c.key,(counts.get(c.key)||0)+1);
    return this.store.transaction(()=>{
      if(this.receipt(turnId))return {written:[],rejected:0};
      if(!this.store.turn(turnId))throw Error('Source removed');
      const written=[];
      for(const c of parsed){
        if(counts.get(c.key)!==1){rejected++;continue;}
        this.db.exec('SAVEPOINT memory_item');
        try{this.validateRevision(c);const id=this.writeChecked(c,turnId);if(id!==null)written.push(id);}
        catch(e){this.db.exec('ROLLBACK TO memory_item');if(e.message!=='Memory revision conflict')throw e;rejected++;conflicts++;}
        finally{this.db.exec('RELEASE memory_item');}
      }
      if(data.length&&!parsed.length)throw Error('All memory candidates invalid');
      if(data.length&&rejected===data.length&&!conflicts)throw Error('All memory candidates rejected');
      this.mark(turnId);return {written,rejected};
    });
  }
}
