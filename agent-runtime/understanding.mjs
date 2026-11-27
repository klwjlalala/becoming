import {randomUUID} from 'node:crypto';
import {completeQuote,terms,SECRET} from './memory.mjs';
import {SCHEMA,UPDATE_PROMPT,UNDERSTANDING_CONTEXT,DIMENSIONS,BASES,EVIDENCE_KINDS,RELATIONS,OPERATIONS,URGENT_CUES,CORRECTION_CUES,PERSONAL_CORRECTION_CUES,PERSONAL_QUERY_CUES,LISTEN_ONLY_CUES,THIRD_PARTY_ONLY_CUES,TRANSIENT_MOOD_CUES} from './understanding-policy.mjs';
const SENSITIVE=/(?:身份证|护照号|银行卡号|信用卡号|诊断|确诊|抑郁|双相障碍|精神分裂|艾滋|HIV|性取向|同性恋|异性恋|宗教|信仰|政治立场|政治倾向|党员|民族|种族|性别认同|婚姻状况)/i;
const has=(s,cues)=>cues.some(c=>s.toLowerCase().includes(c.toLowerCase()));
const obj=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const keys=(v,required,optional=[])=>obj(v)&&required.every(k=>Object.hasOwn(v,k))&&Object.keys(v).every(k=>required.includes(k)||optional.includes(k));
const text=(v,max)=>typeof v==='string'&&v.trim().length>0&&v.length<=max;
const integer=Number.isSafeInteger;
const safe=v=>!SECRET.test(v)&&!SENSITIVE.test(v);
const immutable=['REINFORCE','DISPUTE','REJECT','EXPIRE'];
const now=()=>new Date().toISOString();
const check=(ok,reason)=>{if(!ok)throw Error(reason);};
export function isUrgent(s){return has(s,URGENT_CUES)||(has(s,CORRECTION_CUES)&&has(s,PERSONAL_CORRECTION_CUES));}
// Strict JSON reader rejects duplicate keys rather than accepting last-wins semantics.
export function parseStrictJSON(raw){
  check(typeof raw==='string'&&raw.length<=40000,'Invalid proposal size');
  let s=raw.trim().replace(/^\x60{3}(?:json)?\s*|\s*\x60{3}$/gi,''),i=0;
  const ws=()=>{while(/\s/.test(s[i]||'')&&i<s.length)i++;};
  const string=()=>{const start=i++;while(i<s.length){if(s[i]==='\\'){i+=2;continue;}if(s[i++]==='"')return JSON.parse(s.slice(start,i));}throw Error('Invalid JSON string');};
  const value=(depth=0)=>{check(depth<40,'Too deeply nested');ws();let c=s[i];
    if(c==='"')return string();
    if(c==='{'||c==='['){i++;ws();const isObj=c==='{',end=isObj?'}':']',out=isObj?Object.create(null):[],seen=new Set();if(s[i]===end){i++;return out;}
      while(true){ws();if(isObj){check(s[i]==='"','Invalid key');const k=string();check(!seen.has(k),'Duplicate JSON key');seen.add(k);ws();check(s[i++]===':','Invalid JSON');out[k]=value(depth+1);}else out.push(value(depth+1));ws();if(s[i]===end){i++;return out;}check(s[i++]===',','Invalid JSON');}
    }const m=s.slice(i).match(/^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/);check(m,'Invalid JSON');i+=m[0].length;const v=JSON.parse(m[0]);check(typeof v!=='number'||Number.isFinite(v),'Invalid number');return v;
  };const result=value();ws();check(i===s.length,'Trailing JSON');return result;
}
export function parseProposal(raw,turns,claims,priorByClaim=new Map()){
 const d=parseStrictJSON(raw);check(keys(d,['evidence','operations'],['confirmation']),'Invalid envelope');
 check(Array.isArray(d.evidence)&&d.evidence.length<=24&&Array.isArray(d.operations)&&d.operations.length<=12,'Invalid batch');
 const evidence=new Map(),existing=new Map(claims.map(c=>[c.id,c])),targets=new Set(),aliases=new Set();
 for(const e of d.evidence){
  check(keys(e,['ref','turn_index','quote','kind','event_time']),'Invalid evidence');
  const t=turns[e.turn_index];
  check(typeof e.ref==='string'&&/^e[1-9][0-9]{0,2}$/.test(e.ref)&&!evidence.has(e.ref)&&integer(e.turn_index)&&!!t,'Invalid evidence reference');
  check(text(e.quote,800)&&completeQuote(e.quote,t.user_text)&&safe(e.quote)&&EVIDENCE_KINDS.includes(e.kind),'Invalid source evidence');
  check(e.event_time===null||(typeof e.event_time==='string'&&e.event_time.length<=40&&t.user_text.includes(e.event_time)),'Invalid event time');
  evidence.set(e.ref,e);
 }
 const operations=[];
 for(const op of d.operations){
  check(keys(op,['operation','claim_ref','claim_id','expected_version','content','dimension','basis','scope','temporal_scope','evidence','reason'],['prior_evidence']),'Invalid operation');
  const o=op.operation,old=existing.get(op.claim_id);
  check(OPERATIONS.includes(o)&&text(op.content,500)&&DIMENSIONS.includes(op.dimension)&&BASES.includes(op.basis)&&text(op.temporal_scope,160)&&text(op.reason,400),'Invalid claim');
  check(obj(op.scope)&&Object.keys(op.scope).length<=12&&Object.entries(op.scope).every(([k,v])=>text(k,40)&&(v===null||typeof v==='boolean'||typeof v==='number'||(typeof v==='string'&&v.length<=160))),'Invalid scope');
  check(safe(op.content+' '+op.temporal_scope+' '+JSON.stringify(op.scope))&&safe(op.reason),'Sensitive claim');
  if(o==='CREATE'){check(typeof op.claim_ref==='string'&&/^c[1-9][0-9]{0,2}$/.test(op.claim_ref)&&!aliases.has(op.claim_ref)&&op.claim_id===null&&op.expected_version===null,'Invalid create reference');aliases.add(op.claim_ref);}
  else{check(op.claim_ref===null&&!!old&&integer(op.expected_version)&&old.version===op.expected_version&&!targets.has(op.claim_id),'Unknown/stale claim');targets.add(op.claim_id);}
  const refs=op.evidence,prior=op.prior_evidence===undefined?[]:op.prior_evidence;
  check(Array.isArray(refs)&&refs.length<=12&&Array.isArray(prior)&&prior.length<=12,'Invalid evidence list');
  check(refs.every(r=>keys(r,['ref','relation'])&&evidence.has(r.ref)&&RELATIONS.includes(r.relation))&&new Set(refs.map(r=>r.ref)).size===refs.length,'Invalid evidence relation');
  check(prior.every(r=>keys(r,['evidence_id','relation'])&&integer(r.evidence_id)&&priorByClaim.get(op.claim_id)?.has(r.evidence_id)&&RELATIONS.includes(r.relation))&&new Set(prior.map(r=>r.evidence_id)).size===prior.length,'Invalid prior evidence');
  check(!(o==='CREATE'&&prior.length)&&!(immutable.includes(o)&&prior.length),'Unexpected prior evidence');
  const relations=[...refs,...prior].map(r=>r.relation);
  if(o==='EXPIRE')check(!relations.length,'Expire cannot introduce evidence');else check(relations.length,'Missing evidence');
  if(['CREATE','REFINE','SUPERSEDE','REINFORCE'].includes(o))check(relations.some(r=>r==='support'||r==='qualifies')&&!relations.includes('counter'),'Missing support');
  if(['DISPUTE','REJECT'].includes(o))check(relations.includes('counter'),'Missing counter');
  if(immutable.includes(o))check(old&&op.content===old.content,'Immutable claim text');
  if(o==='REJECT')check(refs.some(r=>evidence.get(r.ref).kind==='correction'),'Explicit correction required');
  operations.push({...op,prior_evidence:prior});
 }
 let confirmation=null,c=d.confirmation;
 if(c!=null){try{
  check(keys(c,['claim_id','claim_ref','expected_version','turn_index','question']),'Invalid confirmation');
  const t=turns[c.turn_index];
  check(integer(c.turn_index)&&t&&text(c.question,240)&&/[?？]/.test(c.question)&&t.assistant_text.includes(c.question),'Question not asked');
  check((c.claim_id===null)!==(c.claim_ref===null),'Invalid target');
  const expected=c.claim_ref!==null?(aliases.has(c.claim_ref)?1:null):existing.get(c.claim_id)?.version;
  check(integer(c.expected_version)&&c.expected_version===expected,'Stale confirmation');confirmation=c;
 }catch{confirmation=null;}}
 return {evidence,operations,confirmation};
}
export class PersonalUnderstanding{
 constructor(store,model){this.store=store;this.model=model;this.db=store.db;this.db.exec(SCHEMA);this.lastSearch=null;
  this.db.exec("UPDATE understanding_jobs SET status='pending' WHERE status='running' AND attempts<3");
  this.db.exec("UPDATE understanding_jobs SET status='failed' WHERE status='running' AND attempts>=3");
  this.db.exec("UPDATE background_jobs SET status='done',error=NULL WHERE kind='personal_understanding.process' AND turn_id IN (SELECT source_turn_id FROM understanding_jobs WHERE status='done')");
 }
 evidence(versionId,limit=1000){return this.db.prepare('SELECT e.*,ce.relation FROM understanding_claim_evidence ce JOIN understanding_evidence e ON e.id=ce.evidence_id WHERE ce.claim_version_id=? ORDER BY e.id DESC LIMIT ?').all(versionId,limit);}
 current(id){const r=this.db.prepare('SELECT c.id,v.version,v.content,v.dimension,v.basis,v.scope_json,v.temporal_scope,v.support_level,v.user_validation,v.status,v.id AS version_id,c.updated_at FROM understanding_claims c JOIN understanding_claim_versions v ON v.claim_id=c.id AND v.version=c.current_version WHERE c.id=?').get(id);return r?this.decode(r):null;}
 decode(r){const {scope_json,...rest}=r;return {...rest,scope:JSON.parse(scope_json)};}
 list(){
  return this.db.prepare("SELECT c.id,v.version,v.content,v.dimension,v.basis,v.scope_json,v.temporal_scope,v.support_level,v.user_validation,v.status,v.id AS version_id,c.updated_at FROM understanding_claims c JOIN understanding_claim_versions v ON v.claim_id=c.id AND v.version=c.current_version WHERE c.status IN ('active','disputed') AND v.status IN ('active','disputed') AND EXISTS(SELECT 1 FROM understanding_claim_evidence ce WHERE ce.claim_version_id=v.id) ORDER BY c.updated_at DESC,c.id").all().map(r=>this.decode(r));
 }
 history(id){return this.db.prepare('SELECT * FROM understanding_claim_versions WHERE claim_id=? ORDER BY version').all(id).map(v=>({...v,evidence:this.evidence(v.id)}));}
 revisions(id){return this.db.prepare('SELECT * FROM understanding_revisions WHERE claim_id=? ORDER BY id').all(id);}
 overlap(q,c,n=4){const x=terms(c.content+' '+this.evidence(c.version_id,n).map(e=>e.quote).join(' ')+' '+JSON.stringify(c.scope));return [...q].filter(t=>x.has(t)).length;}
 retrieve(query,limit=7){
  check(integer(limit)&&limit>=0&&limit<=7,'Invalid limit');if(!query.trim()||!limit)return [];
  const reflective=has(query,PERSONAL_QUERY_CUES);
  const suppression=has(query,LISTEN_ONLY_CUES)?'listen_only':has(query,THIRD_PARTY_ONLY_CUES)&&!has(query,['我自己','我也','我为什么','我感到','让我','对我来说'])?'third_party_only':has(query,TRANSIENT_MOOD_CUES)&&!reflective?'transient_mood':null;
  if(suppression){this.lastSearch={candidate_ids:[],selected_ids:[],query_mode:'suppressed',suppression_reason:suppression};return [];}
  const claims=this.list(),q=terms(query);
  const selected=claims.map(c=>{let score=this.overlap(q,c);if(score)score+=2+(c.support_level==='high'?1:0);if(reflective)score+=3;
   if(has(query,['取舍','约束','收入','稳定','现实'])&&['constraints','tensions'].includes(c.dimension))score+=3;
   if(has(query,['真正想要','想要的生活','价值观','人生意义','人生方向'])){if(['values','motivation','needs','goals'].includes(c.dimension))score+=2;if(this.evidence(c.version_id).some(e=>e.kind==='experience'&&e.relation!=='counter'))score+=3;}
   if(has(query,['变化','改变','以前和现在'])&&['cognition','self_concept','patterns'].includes(c.dimension))score+=2;
   if(c.status==='disputed')score--;return {c,score};}).filter(x=>x.score>0).sort((a,b)=>b.score-a.score||b.c.updated_at.localeCompare(a.c.updated_at)).slice(0,limit).map(x=>x.c);
  this.lastSearch={candidate_ids:claims.map(c=>c.id),selected_ids:selected.map(c=>c.id),query_mode:reflective?'reflective':'lexical'};return selected;
 }
 payload(c,withIds=false){const {id,version_id,updated_at,...fields}=c;return {claim_id:id,...fields,evidence:this.evidence(version_id,4).map(e=>({...(withIds?{evidence_id:e.id}:{}),quote:e.quote,kind:e.kind,relation:e.relation,recorded_at:e.recorded_at,event_time:e.event_time}))};}
 context(claims){const p=claims.slice(0,7).map(c=>this.payload(c));while(JSON.stringify(p).length>6000&&p.length)p.pop();return UNDERSTANDING_CONTEXT+'\n'+JSON.stringify(p);}
 support(versionId,validation){const evidence=this.evidence(versionId),supports=evidence.filter(e=>e.relation!=='counter');if(evidence.some(e=>e.relation==='counter'))return 'low';if(validation==='confirmed')return 'high';const n=new Set(supports.map(e=>e.source_turn_id)).size,dates=new Set(supports.map(e=>e.recorded_at.slice(0,10))).size;return n>=3&&dates>=2?'high':n>=2?'medium':'low';}
 insertEvidence(turn,e){this.db.prepare('INSERT OR IGNORE INTO understanding_evidence(source_turn_id,quote,kind,event_time,recorded_at) VALUES(?,?,?,?,?)').run(turn.turn_id,e.quote,e.kind,e.event_time,turn.recorded_at);return this.db.prepare('SELECT id FROM understanding_evidence WHERE source_turn_id=? AND quote=?').get(turn.turn_id,e.quote).id;}
 link(v,e,relation){this.db.prepare('INSERT OR IGNORE INTO understanding_claim_evidence VALUES(?,?,?)').run(v,e,relation);}
 writeVersion(id,old,fields,status,validation,operation,reason,links,carry){
  const time=now(),version=(old?.version||0)+1;
  if(old)this.db.prepare("UPDATE understanding_claim_versions SET status='superseded' WHERE id=?").run(old.version_id);
  const v=Number(this.db.prepare("INSERT INTO understanding_claim_versions(claim_id,version,content,dimension,basis,scope_json,temporal_scope,support_level,user_validation,status,revision_reason,created_at) VALUES(?,?,?,?,?,?,?,'low',?,?,?,?)").run(id,version,fields.content,fields.dimension,fields.basis,JSON.stringify(fields.scope),fields.temporal_scope,validation,status,reason,time).lastInsertRowid);
  if(old&&carry)this.db.prepare('INSERT INTO understanding_claim_evidence SELECT ?,evidence_id,relation FROM understanding_claim_evidence WHERE claim_version_id=?').run(v,old.version_id);
  for(const [e,r] of links)this.link(v,e,r);
  const evidence=this.evidence(v);check(evidence.length,'Claim version lacks evidence');
  this.db.prepare('UPDATE understanding_claim_versions SET support_level=? WHERE id=?').run(this.support(v,validation),v);
  this.db.prepare('UPDATE understanding_claims SET current_version=?,status=?,updated_at=? WHERE id=?').run(version,status,time,id);
  const rev=Number(this.db.prepare('INSERT INTO understanding_revisions(claim_id,from_version_id,to_version_id,operation,reason,created_at) VALUES(?,?,?,?,?,?)').run(id,old?.version_id??null,v,operation,reason,time).lastInsertRowid);
  for(const e of new Set(links.length?links.map(x=>x[0]):[evidence[0].id]))this.db.prepare('INSERT INTO understanding_revision_evidence VALUES(?,?)').run(rev,e);
  return v;
 }
 apply(proposal,turns){
  const aliases=new Map(),ids=new Map(),written=[];
  const evidenceId=ref=>{if(!ids.has(ref)){const e=proposal.evidence.get(ref);ids.set(ref,this.insertEvidence(turns[e.turn_index],e));}return ids.get(ref);};
  for(const op of proposal.operations){
   const operation=op.operation,isNew=operation==='CREATE';let id=op.claim_id,old=null;
   if(isNew){id=randomUUID().replace(/-/g,'');this.db.prepare("INSERT INTO understanding_claims(id,current_version,status,created_at,updated_at) VALUES(?,0,'active',?,?)").run(id,now(),now());aliases.set(op.claim_ref,id);}
   else{old=this.current(id);check(old&&old.version===op.expected_version,'Claim changed during update');}
   const carry=immutable.includes(operation);if(carry)check(old&&old.content===op.content,'Immutable claim text');
   const fields=carry?old:op,status={DISPUTE:'disputed',REJECT:'rejected',EXPIRE:'expired'}[operation]||'active';
   const validation=['CREATE','REFINE','SUPERSEDE'].includes(operation)?'unconfirmed':operation==='REJECT'?'rejected':old.user_validation;
   const links=[...op.prior_evidence.map(e=>[e.evidence_id,e.relation]),...op.evidence.map(e=>[evidenceId(e.ref),e.relation])];
   this.writeVersion(id,old,fields,status,validation,operation,op.reason,links,carry);written.push(id);
  }
  const c=proposal.confirmation;
  if(c){const id=c.claim_id??aliases.get(c.claim_ref),current=this.current(id);
   if(current&&current.version===c.expected_version){
    this.db.prepare("UPDATE understanding_pending_confirmations SET status='expired',resolved_at=? WHERE claim_id=? AND status='pending'").run(now(),id);
    this.db.prepare("INSERT INTO understanding_pending_confirmations(claim_id,claim_version_id,source_turn_id,question,status,created_at) VALUES(?,?,?,?,'pending',?)").run(id,current.version_id,turns[c.turn_index].turn_id,c.question,now());
   }
  }return written;
 }
 enqueue(turnId){
  const t=this.store.turn(turnId);check(t,'Missing source');this.db.prepare("INSERT OR IGNORE INTO understanding_jobs(job_key,source_turn_id,kind,status,created_at,updated_at) VALUES(?,?,?,'pending',?,?)").run('turn:'+turnId,turnId,isUrgent(t.user)?'immediate':'normal',now(),now());
 }
 async processPending(targetId=null){
  const jobs=this.db.prepare("SELECT j.id AS job_id,t.id AS turn_id,t.user AS user_text,t.assistant AS assistant_text,t.created_at AS recorded_at FROM understanding_jobs j JOIN turns t ON t.id=j.source_turn_id WHERE j.status IN ('pending','failed') AND j.attempts<3 ORDER BY CASE WHEN j.source_turn_id=? THEN -1 WHEN j.kind='immediate' THEN 0 ELSE 1 END,j.id LIMIT 5").all(targetId);
  if(!jobs.length)return [];
  const q=terms(jobs.map(t=>t.user_text).join('\n')),claims=this.list().sort((a,b)=>this.overlap(q,b,3)-this.overlap(q,a,3)||b.updated_at.localeCompare(a.updated_at)).slice(0,15),prior=new Map(claims.map(c=>[c.id,new Set(this.evidence(c.version_id,4).map(e=>e.id))]));
  const payload={turns:jobs.map((t,i)=>({turn_index:i,source_turn_id:t.turn_id,user_text:t.user_text,assistant_text:t.assistant_text,recorded_at:t.recorded_at})),current_claims:claims.map(c=>this.payload(c,true)),rules:{max_turns:5,no_write_is_valid:true,source_of_evidence:'user_text_only'}};
  this.store.transaction(()=>{for(const j of jobs)this.db.prepare("UPDATE understanding_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?").run(now(),j.job_id);});
  try{
   const raw=await this.model.complete([{role:'system',content:UPDATE_PROMPT},{role:'user',content:JSON.stringify(payload)}]),proposal=parseProposal(raw,jobs,claims,prior);
   const written=this.store.transaction(()=>{for(const j of jobs)check(this.store.turn(j.turn_id),'Source removed');const ids=this.apply(proposal,jobs);for(const j of jobs)this.db.prepare("UPDATE understanding_jobs SET status='done',last_error=NULL,updated_at=? WHERE id=?").run(now(),j.job_id);return ids;});
   return written;
  }catch(e){this.store.transaction(()=>{for(const j of jobs)this.db.prepare("UPDATE understanding_jobs SET status='failed',last_error='update_failed',updated_at=? WHERE id=?").run(now(),j.job_id);});throw e;}
 }
 async processTurn(id){
  // Register already queued turns before choosing a batch. All source turns
  // were durably committed by the Agent; acknowledgements remain per turn.
  this.enqueue(id);
  for(const j of this.db.prepare("SELECT turn_id FROM background_jobs WHERE kind='personal_understanding.process' AND status IN ('pending','running') ORDER BY priority DESC,id LIMIT 20").all())this.enqueue(j.turn_id);
  const status=()=>this.db.prepare('SELECT status,attempts FROM understanding_jobs WHERE source_turn_id=?').get(id);
  if(status().status!=='done'){check(status().attempts<3,'Understanding attempts exhausted');await this.processPending(id);}
  this.resolveDeferred();check(status().status==='done','Understanding job not completed');
 }
 confirmationKind(s){
  if(/^(?:不是|不对|并非|你理解错了|我不认可|我不同意|no|incorrect)(?:$|[，,。！？!?；;：:\s])/i.test(s.trim()))return 'rejected';
  if(/^(?:是的|对(?:的)?|没错|确实|就是这样|可以这么理解|我认可|我同意|yes|correct)(?:$|[，,。！？!?；;：:\s])/i.test(s.trim()))return 'confirmed';
  return null;
 }
 resolve(turnId){
  const t=this.store.turn(turnId);if(!t)return [];
  return this.store.transaction(()=>{
   const currentRow=this.db.prepare('SELECT rowid AS seq FROM turns WHERE id=?').get(turnId).seq;
   const pending=this.db.prepare("SELECT p.*,source.rowid AS seq FROM understanding_pending_confirmations p JOIN turns source ON source.id=p.source_turn_id WHERE p.status='pending' AND source.conversation_id=? ORDER BY p.id DESC").all(t.conversation_id);
   let eligible=null;
   for(const p of pending){const n=this.db.prepare('SELECT rowid AS seq,id FROM turns WHERE conversation_id=? AND rowid>? ORDER BY rowid LIMIT 1').get(t.conversation_id,p.seq);if(!n||n.seq>currentRow)continue;if(n.id===turnId&&!eligible){eligible=p;continue;}this.db.prepare("UPDATE understanding_pending_confirmations SET status='expired',resolved_at=? WHERE id=?").run(now(),p.id);}
   if(!eligible)return [];
   const p=eligible,old=this.current(p.claim_id),kind=this.confirmationKind(t.user);
   if(!kind||!old||old.version_id!==p.claim_version_id||!safe(t.user)||t.user.length>800){this.db.prepare("UPDATE understanding_pending_confirmations SET status='expired',resolved_at=? WHERE id=?").run(now(),p.id);return [];}
   const e=this.insertEvidence({turn_id:t.id,recorded_at:t.created_at},{quote:t.user,kind:'correction',event_time:null});
   this.writeVersion(old.id,old,old,kind==='confirmed'?'active':'rejected',kind,kind==='confirmed'?'CONFIRM':'REJECT',kind==='confirmed'?'用户明确确认':'用户明确否定',[[e,kind==='confirmed'?'support':'counter']],true);
   this.db.prepare("UPDATE understanding_pending_confirmations SET status=?,resolved_at=? WHERE id=?").run(kind,now(),p.id);return [old.id];
  });
 }
 resolveDeferred(){const rows=this.db.prepare("SELECT DISTINCT next.id,next.rowid AS seq FROM understanding_pending_confirmations p JOIN turns source ON source.id=p.source_turn_id JOIN turns next ON next.rowid=(SELECT MIN(rowid) FROM turns WHERE conversation_id=source.conversation_id AND rowid>source.rowid) WHERE p.status='pending' ORDER BY seq").all();return rows.flatMap(r=>this.resolve(r.id));}
}
