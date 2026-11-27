import {createServer} from 'node:http';
import {readFileSync,mkdirSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {Store} from './store.mjs';
import {Agent,Gateway,BackgroundWorker} from './agent.mjs';
import {LongMemory} from './memory.mjs';
import {HistoricalMemory} from './memory-search.mjs';
import {PersonalUnderstanding} from './understanding.mjs';
import {GrowthStore,GrowthTools} from './growth.mjs';
const port=Number(process.env.BECOMING_LOCAL_PORT||4310);
const host='127.0.0.1:'+port;
const path=resolve(process.env.BECOMING_LOCAL_DB||'data/agent-local.sqlite3');
mkdirSync(dirname(path),{recursive:true});
const store=new Store(path);
const gateway=new Gateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000');
const memoryMode=process.env.BECOMING_MEMORY_MODE||'lexical';
if(!['lexical','semantic','historical','improved'].includes(memoryMode))throw Error('Invalid memory mode');
const memory=process.env.BECOMING_ENABLE_LONG_MEMORY==='0'?null: ['historical','improved'].includes(memoryMode)?new HistoricalMemory(store,gateway,{improved:memoryMode==='improved',embedder:process.env.BECOMING_ENABLE_EMBEDDINGS==='1'?gateway:null}):new LongMemory(store,gateway,{semantic:memoryMode==='semantic'});
const understanding=process.env.BECOMING_ENABLE_PERSONAL_UNDERSTANDING==='0'?null:new PersonalUnderstanding(store,gateway);
const growthPath=resolve(process.env.BECOMING_LOCAL_GROWTH_DB||path+'.growth.sqlite3');
if(growthPath===path)throw Error('Growth and transcript databases must be separate');
mkdirSync(dirname(growthPath),{recursive:true});
const growth=new GrowthTools(gateway,new GrowthStore(growthPath));
const agent=new Agent(store,gateway,{memory,understanding,growth});
const worker=new BackgroundWorker(store,{'long_memory.extract':id=>{if(!memory)throw Error('Memory disabled');return memory.extract(id);},'personal_understanding.process':id=>{if(!understanding)throw Error('Understanding disabled');return understanding.processTurn(id);}});
setInterval(()=>{void worker.tick();},1000).unref();
const assets=new Map([['/',['text/html; charset=utf-8','index.html']],['/app.js',['text/javascript; charset=utf-8','app.js']],['/style.css',['text/css; charset=utf-8','style.css']]]);
function json(res,status,body){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(body));}
async function body(req){
  let data='';for await(const chunk of req){data+=chunk;if(Buffer.byteLength(data)>100000)throw Error('Request too large');}
  return JSON.parse(data);
}
createServer(async(req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Content-Security-Policy',"default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'");
  if(req.headers.host!==host || (req.headers.origin && req.headers.origin!=='http://'+host))return json(res,403,{error:'Forbidden origin'});
  const url=new URL(req.url,'http://'+host),p=url.pathname;
  if(req.method==='GET'&&assets.has(p)){
    const [type,file]=assets.get(p);res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store'});return res.end(readFileSync(new URL('../web/'+file,import.meta.url)));
  }
  if(req.method==='GET'&&p==='/api/conversations')return json(res,200,{conversations:store.conversations()});
  if(req.method==='GET'&&p==='/api/history'){
    const id=url.searchParams.get('conversation_id')||'default';try{return json(res,200,{turns:store.history(200,id),pending_growth:growth.getPending(id)});}catch{return json(res,404,{error:'Unknown conversation'});}
  }
  if(req.method==='GET'&&p==='/api/status')return json(res,200,{jobs:store.jobCounts(),memoryEnabled:!!memory});
  if(req.method==='GET'&&p==='/api/memories')return json(res,200,{memories:memory?.list()||[]});
  if(req.method==='GET'&&p==='/api/understanding')return json(res,200,{claims:understanding?.list()||[]});
  if(req.method==='GET'&&p==='/api/jobs')return json(res,200,{jobs:store.jobs()});
  if(req.method==='POST'&&p==='/api/conversations'){
    if(req.headers.origin!=='http://'+host||!req.headers['content-type']?.startsWith('application/json'))return json(res,403,{error:'Invalid request origin'});
    try{const b=await body(req);return json(res,201,{conversation:store.createConversation(b.title)});}catch{return json(res,400,{error:'Invalid conversation'});}
  }
  if(req.method==='POST'&&p==='/api/chat'){
    if(req.headers.origin!=='http://'+host||!req.headers['content-type']?.startsWith('application/json'))return json(res,403,{error:'Invalid request origin'});
    let input,id;try{const b=await body(req);input=b.text;id=b.conversation_id??'default';store.requireConversation(id);if(typeof input!=='string'||!input.trim()||input.length>16000)throw Error();}
    catch{return json(res,400,{error:'Invalid input'});}
    try{return json(res,200,{turn:await agent.reply(input,id)});}
    catch{return json(res,502,{error:'Agent request failed; no incomplete turn saved'});}
  }
  return json(res,404,{error:'Not found'});
}).listen(port,'127.0.0.1',()=>console.log('Becoming local runtime: http://'+host));
