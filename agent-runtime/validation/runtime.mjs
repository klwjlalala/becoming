import {Gateway,Agent,BackgroundWorker} from '../agent.mjs';
import {Store} from '../store.mjs';
import {LongMemory} from '../memory.mjs';
import {PersonalUnderstanding} from '../understanding.mjs';
import {GrowthStore,GrowthTools} from '../growth.mjs';
export class BudgetedModel{
 constructor(limit=60){this.limit=limit;this.calls=0;this.timings=[];this.gateway=new Gateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000');}
 async complete(messages){if(this.calls>=this.limit)throw Error('Model call budget exhausted');this.calls++;const start=performance.now();try{return await this.gateway.complete(messages);}finally{this.timings.push(Math.round(performance.now()-start));}}
}
export function runtime(model,{memory=false,semantic=false,understanding=false,growth=false,historyTurns=0}={}){
 const store=new Store(':memory:'),m=memory?new LongMemory(store,model,{semantic}):null,u=understanding?new PersonalUnderstanding(store,model):null,g=growth?new GrowthStore(':memory:'):null,tools=g?new GrowthTools(model,g):null;
 const agent=new Agent(store,model,{memory:m,understanding:u,growth:tools,historyTurns});
 const worker=new BackgroundWorker(store,{'long_memory.extract':id=>m.extract(id),'personal_understanding.process':id=>u.processTurn(id)});
 async function drain(){for(let i=0;i<200;i++){if(!await worker.tick())break;}const c=store.jobCounts();if(c.pending||c.running||c.failed)throw Error('Background jobs did not complete: '+JSON.stringify(c));}
 async function reply(text,{day,process=true}={}){const t=await agent.reply(text);if(day&&t.id)store.db.prepare('UPDATE turns SET created_at=? WHERE id=?').run(day+'T12:00:00Z',t.id);if(process)await drain();return t;}
 return {store,m,u,g,agent,worker,reply,drain,close(){g?.close();store.close();}};
}
