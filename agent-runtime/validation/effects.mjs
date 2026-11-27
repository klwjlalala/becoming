import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {dirname} from 'node:path';
import {BudgetedModel,runtime} from './runtime.mjs';
const cases=JSON.parse(readFileSync(new URL('../../evaluation/cases.json',import.meta.url),'utf8'));
const longitudinal=JSON.parse(readFileSync(new URL('../../evaluation/personal_understanding_cases.json',import.meta.url),'utf8'));
export function validateFixtures(){
 if(!Array.isArray(cases)||!cases.length||cases.some(c=>!c.id||!c.turns?.length||!c.criteria?.length||c.turns.some(t=>typeof t!=='string'||!t.trim())))throw Error('Invalid effect cases');
 if(longitudinal.fictional!==true||longitudinal.turns.length!==30||longitudinal.turns.some((t,i)=>!t.text?.trim()||(i&&t.day<=longitudinal.turns[i-1].day)||(t.evidence||[]).some(e=>!t.text.includes(e.quote))))throw Error('Invalid longitudinal fixture');
 return {cases:cases.length,longitudinal_turns:longitudinal.turns.length};
}
const validation=validateFixtures();console.log('Fixture validation:',JSON.stringify(validation));
if(process.argv.includes('--live')){
 const mode=process.env.BECOMING_EFFECT_MODE||'longitudinal',model=new BudgetedModel(mode==='longitudinal'?70:80),report={mode,validation,fictional_data_only:true,automatic_quality_verdict:null,model_calls:0,results:[]};
 const out=process.env.BECOMING_REPORT||'artifacts/node-effects.json';
 function save(){report.model_calls=model.calls;report.max_calls=model.limit;report.call_durations_ms=model.timings;mkdirSync(dirname(out),{recursive:true});writeFileSync(out,JSON.stringify(report,null,2)+'\n');}
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
 }else throw Error('Invalid effect mode');
 }catch(e){report.error=e.message;process.exitCode=1;}finally{save();console.log('Report saved; semantic quality requires manual review. Calls:',model.calls);}
}
