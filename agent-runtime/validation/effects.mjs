import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {BudgetedModel,runtime} from './runtime.mjs';
import {Agent} from '../agent.mjs';
const cases=JSON.parse(readFileSync(new URL('../../evaluation/cases.json',import.meta.url),'utf8'));
const longitudinal=JSON.parse(readFileSync(new URL('../../evaluation/personal_understanding_cases.json',import.meta.url),'utf8'));
export function validateFixtures(){
 if(!Array.isArray(cases)||!cases.length||cases.some(c=>!c.id||!c.turns?.length||!c.criteria?.length||c.turns.some(t=>typeof t!=='string'||!t.trim())))throw Error('Invalid effect cases');
 if(longitudinal.fictional!==true||longitudinal.turns.length!==30||longitudinal.turns.some((t,i)=>!t.text?.trim()||(i&&t.day<=longitudinal.turns[i-1].day)||(t.evidence||[]).some(e=>!t.text.includes(e.quote))))throw Error('Invalid longitudinal fixture');
 return {cases:cases.length,longitudinal_turns:longitudinal.turns.length};
}
const validation=validateFixtures();console.log('Fixture validation:',JSON.stringify(validation));
if(process.argv.includes('--live')){
 const mode=process.env.BECOMING_EFFECT_MODE||'longitudinal',model=new BudgetedModel(mode==='longitudinal'?70:mode==='long-session'?100:80),report={mode,validation,fictional_data_only:true,automatic_quality_verdict:null,model_calls:0,results:[]};
 const out=process.env.BECOMING_REPORT||'artifacts/node-effects.json';
 function save(){report.model_calls=model.calls;report.max_calls=model.limit;report.call_durations_ms=model.timings;report.trace=model.trace;mkdirSync(dirname(out),{recursive:true});writeFileSync(out,JSON.stringify(report,null,2)+'\n');}
 try{
 if(mode==='longitudinal'){
  const r=runtime(model,{understanding:true,historyTurns:0}),baseline=runtime(model,{historyTurns:0});
  const result={id:longitudinal.id,turns:[],expected_understandings:longitudinal.expected_understandings,review_criteria:longitudinal.review_criteria};report.results.push(result);
  try{
   for(const t of longitudinal.turns){const turn=await r.reply(t.text,{day:t.day});result.turns.push({day:t.day,turn,jobs:r.store.jobs(turn.id),claims:r.u.list()});save();}
   result.claims=r.u.list().map(c=>({claim:c,history:r.u.history(c.id),revisions:r.u.revisions(c.id)}));
   result.final_answer=result.turns.at(-1).turn.assistant;result.baseline_final=(await baseline.reply(longitudinal.turns.at(-1).text)).assistant;
   console.log('Longitudinal summary: '+JSON.stringify({turn_count:result.turns.length,active_claims:result.claims.length,final_answer:result.final_answer,baseline_final:result.baseline_final,final_retrieval:result.turns.at(-1).turn.event.retrieved_claim_ids}));
  }finally{r.close();baseline.close();}
 }else if(mode==='scenarios'){
  for(const c of cases){
   const r=runtime(model,{memory:!!c.long_memory,semantic:!!c.semantic_memory,historyTurns:c.long_memory?0:12});
   const result={id:c.id,criteria:c.criteria,turns:[]};report.results.push(result);
   try{for(const user of c.turns){const turn=await r.reply(user);result.turns.push({turn,jobs:r.store.jobs(turn.id),memories:r.m?.list(false)||[]});save();}console.log('Scenario summary: '+JSON.stringify({id:c.id,turn_count:result.turns.length,final_answer:result.turns.at(-1).turn.assistant,retrieved_ids:result.turns.at(-1).turn.event.retrieved_memory_ids}));}finally{r.close();}
  }

 }else if(mode==='long-session'){
  const r=runtime(model,{memory:true,understanding:true,historyTurns:12});
  const result={
   id:longitudinal.id,
   evaluation:'integrated-long-session',
   fixture_turns:longitudinal.turns.length,
   history_window:12,
   enabled_modules:['long_memory','personal_understanding'],
   disabled_modules:['growth_tools'],
   expected_understandings:longitudinal.expected_understandings,
   review_criteria:longitudinal.review_criteria,
   turns:[],
   no_write_checks:[]
  };
  let baseline=null;
  report.results.push(result);
  try{
   for(let i=0;i<longitudinal.turns.length;i++){
    const fixture=longitudinal.turns[i];
    if(i===longitudinal.turns.length-1){
     baseline=runtime(model,{historyTurns:12});
     const context=r.store.history(12);
     result.baseline_context_turns=context.map(t=>({user:t.user,assistant:t.assistant}));
     for(const previous of context)baseline.store.append(previous.user,previous.assistant);
    }
    const turn=await r.reply(fixture.text,{day:fixture.day,process:false});
    if(turn.event?.errors?.length)throw Error('Feature retrieval failed on '+fixture.day+': '+JSON.stringify(turn.event.errors));
    result.turns.push({
     day:fixture.day,
     user:fixture.text,
     assistant:turn.assistant,
     turn_id:turn.id,
     event:turn.event
    });
    if((i+1)%5===0||i===longitudinal.turns.length-1){
     await r.drain();
     for(const item of result.turns.slice(-5))item.jobs=r.store.jobs(item.turn_id);
    }
    save();
   }

   const noWrite=longitudinal.turns.map((fixture,index)=>({fixture,index})).filter(x=>x.fixture.no_write===true);
   for(const {fixture,index} of noWrite){
    const turnId=result.turns[index].turn_id;
    const memoryRows=r.store.db.prepare('SELECT COUNT(*) AS count FROM long_memories WHERE source_turn_id=?').get(turnId).count;
    const evidenceRows=r.store.db.prepare('SELECT COUNT(*) AS count FROM understanding_evidence WHERE source_turn_id=?').get(turnId).count;
    result.no_write_checks.push({day:fixture.day,memory_rows:memoryRows,understanding_evidence_rows:evidenceRows});
   }
   const invalidNoWrite=result.no_write_checks.filter(x=>x.memory_rows||x.understanding_evidence_rows);
   if(invalidNoWrite.length)throw Error('No-write turns produced persisted personal data: '+JSON.stringify(invalidNoWrite));

   const correctionIndex=longitudinal.turns.findIndex(t=>t.text.includes('你之前总把我理解成想创业'));
   if(correctionIndex<0)throw Error('Correction fixture is missing');
   const correctionTurnId=result.turns[correctionIndex].turn_id;
   const correctionEvidenceRows=r.store.db.prepare('SELECT COUNT(*) AS count FROM understanding_evidence WHERE source_turn_id=?').get(correctionTurnId).count;
   result.correction_evidence_rows=correctionEvidenceRows;
   if(!correctionEvidenceRows)throw Error('Explicit correction did not produce traceable personal-understanding evidence');

   const completedJobs=r.store.jobCounts();
   result.completed_job_counts=completedJobs;
   if(completedJobs.pending||completedJobs.running||completedJobs.failed)throw Error('Background processing did not finish cleanly: '+JSON.stringify(completedJobs));

   const finalTurn=result.turns.at(-1);
   result.final_answer=finalTurn.assistant;
   result.final_retrieved_claim_ids=finalTurn.event.retrieved_claim_ids;
   result.final_retrieved_memory_ids=finalTurn.event.retrieved_memory_ids;
   if(!result.final_retrieved_claim_ids?.length)throw Error('Final synthesis did not retrieve personal-understanding claims');
   const allClaims=r.u.list();
   result.final_retrieved_claims=allClaims.filter(c=>result.final_retrieved_claim_ids.includes(c.id)).map(c=>({claim:c,history:r.u.history(c.id),revisions:r.u.revisions(c.id)}));
   result.final_retrieved_memories=r.m.list(false).filter(m=>result.final_retrieved_memory_ids.includes(m.id));
   result.active_memories=r.m.list();
   result.active_claims=allClaims.map(c=>({claim:c,history:r.u.history(c.id),revisions:r.u.revisions(c.id)}));

   const baselineTurn=await baseline.agent.reply(longitudinal.turns.at(-1).text);
   result.baseline_final=baselineTurn.assistant;

   const autonomyMemory=r.m.list().find(m=>m.quote.includes('自己安排时间')||m.quote.includes('职位头衔'));
   if(!autonomyMemory)throw Error('Early autonomy preference was not extracted into long-term memory');
   const probeAgent=new Agent(r.store,model,{memory:r.m,historyTurns:0});
   const probeText='我之前提到过，比起职位头衔，我更在意什么？请根据我之前说过的话简短回答。';
   const probe=await probeAgent.reply(probeText);
   const retrievedTarget=probe.event.retrieved_memory_ids.includes(autonomyMemory.id);
   result.memory_probe={
    history_window:0,
    user:probeText,
    assistant:probe.assistant,
    target_memory:autonomyMemory,
    retrieved_memory_ids:probe.event.retrieved_memory_ids,
    retrieved_target_memory:retrievedTarget
   };
   if(!retrievedTarget)throw Error('Long-term memory did not retrieve the early autonomy preference after 30 turns');
   r.store.db.prepare('DELETE FROM turns WHERE id=?').run(probe.id);
   result.final_job_counts=r.store.jobCounts();

   console.log('Long-session summary: '+JSON.stringify({
    turns:result.turns.length,
    model_calls:model.calls,
    active_memories:result.active_memories.length,
    active_claims:result.active_claims.length,
    no_write_checks:result.no_write_checks.length,
    correction_evidence_rows:correctionEvidenceRows,
    final_retrieved_claims:result.final_retrieved_claim_ids.length,
    early_memory_retrieved:retrievedTarget,
    baseline_answer_characters:result.baseline_final.length,
    integrated_answer_characters:result.final_answer.length
   }));
  }finally{
   baseline?.close();
   r.close();
  }
 }else throw Error('Invalid effect mode');
 }catch(e){report.error=e.message;process.exitCode=1;}finally{save();console.log('Report saved; semantic quality requires manual review. Calls:',model.calls);}
}
