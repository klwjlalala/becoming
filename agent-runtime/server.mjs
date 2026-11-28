import {createServer} from 'node:http';
import {readFileSync,mkdirSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {randomUUID} from 'node:crypto';
import {Store} from './store.mjs';
import {Agent,Gateway,BackgroundWorker} from './agent.mjs';
import {LongMemory} from './memory.mjs';
import {HistoricalMemory} from './memory-search.mjs';
import {PersonalUnderstanding} from './understanding.mjs';
import {GrowthStore,GrowthTools} from './growth.mjs';
import {CapabilityRegistry} from './capabilities/registry.mjs';
import {AssetStore} from './assets.mjs';
const port=Number(process.env.BECOMING_LOCAL_PORT||4310);
const host='127.0.0.1:'+port;
const path=resolve(process.env.BECOMING_LOCAL_DB||'data/agent-local.sqlite3');
mkdirSync(dirname(path),{recursive:true});
const store=new Store(path);
const assetStore=new AssetStore(store,process.env.BECOMING_ASSET_DIR||path+'.assets');
const gateway=new Gateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000');
const memoryMode=process.env.BECOMING_MEMORY_MODE||'lexical';
if(!['lexical','semantic','historical','improved'].includes(memoryMode))throw Error('Invalid memory mode');
const memory=process.env.BECOMING_ENABLE_LONG_MEMORY==='0'?null:['historical','improved'].includes(memoryMode)?new HistoricalMemory(store,gateway,{improved:memoryMode==='improved',embedder:process.env.BECOMING_ENABLE_EMBEDDINGS==='1'?gateway:null}):new LongMemory(store,gateway,{semantic:memoryMode==='semantic'});
const understanding=process.env.BECOMING_ENABLE_PERSONAL_UNDERSTANDING==='0'?null:new PersonalUnderstanding(store,gateway);
const growthPath=resolve(process.env.BECOMING_LOCAL_GROWTH_DB||path+'.growth.sqlite3');
if(growthPath===path)throw Error('Growth and transcript databases must be separate');
mkdirSync(dirname(growthPath),{recursive:true});
const growth=new GrowthTools(gateway,new GrowthStore(growthPath));
const capabilities=new CapabilityRegistry();
growth.registerCapabilities(capabilities);
capabilities.register({
  name:'chart_create',
  description:'Create a visual chart from structured data. Use for comparing values or showing trends; supports bar, line and pie charts.',
  category:'visualization',
  keywords:['图表','数据可视化','趋势','比较','chart','visualization'],
  parameters:{
    type:'object',
    properties:{
      title:{type:'string',minLength:1,maxLength:120},
      chart_type:{type:'string',enum:['bar','line','pie']},
      labels:{type:'array',minItems:1,maxItems:16,items:{type:'string',minLength:1,maxLength:80}},
      values:{type:'array',minItems:1,maxItems:16,items:{type:'number',minimum:0,maximum:1000000}}
    },
    required:['title','chart_type','labels','values'],
    additionalProperties:false
  },
  handler:args=>{
    if(args.labels.length!==args.values.length)throw Error('Chart labels and values must have the same length');
    return {blocks:[{type:'chart',chartType:args.chart_type,title:args.title,labels:args.labels,values:args.values}]};
  }
});
capabilities.register({
    name:'image_generate',
    description:'Generate an original image to illustrate a scene, idea or concept. Use when a visual would materially help the user; describe the intended image precisely.',
    category:'visualization',
    keywords:['图片生成','画图','插画','场景图','image generation','illustration','visual'],
    parameters:{
      type:'object',
      properties:{
        prompt:{type:'string',minLength:8,maxLength:4000},
        size:{type:'string',enum:['1024x1024','1024x1536','1536x1024']},
        alt:{type:'string',maxLength:300},
        caption:{type:'string',maxLength:500}
      },
      required:['prompt'],
      additionalProperties:false
    },
    handler:async args=>{
      const generated=await gateway.generateImage({prompt:args.prompt,size:args.size||'1024x1024'});
      const asset=assetStore.save(generated.buffer,generated.mime_type);
      return {asset_id:asset.id,mime_type:asset.mime_type,blocks:[{type:'image',asset_id:asset.id,alt:args.alt||'AI 生成的辅助图片',caption:args.caption||generated.revised_prompt||''}]};
    }
});
const agent=new Agent(store,gateway,{memory,understanding,growth,capabilities});
const worker=new BackgroundWorker(store,{'long_memory.extract':id=>{if(!memory)throw Error('Memory disabled');return memory.extract(id);},'personal_understanding.process':id=>{if(!understanding)throw Error('Understanding disabled');return understanding.processTurn(id);}});
setInterval(()=>{worker.tick().catch(()=>console.error('Background worker tick failed'));},1000).unref();
const assets=new Map([['/',['text/html; charset=utf-8','index.html']],['/app.js',['text/javascript; charset=utf-8','app.js']],['/style.css',['text/css; charset=utf-8','style.css']]]);
function json(res,status,body){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(body));}
function event(res,name,data){if(!res.destroyed&&!res.writableEnded)res.write('event: '+name+'\ndata: '+JSON.stringify(data)+'\n\n');}
async function body(req){
  let data='';for await(const chunk of req){data+=chunk;if(Buffer.byteLength(data)>100000)throw Error('Request too large');}
  return JSON.parse(data);
}
createServer(async(req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');
  res.setHeader('Content-Security-Policy',"default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'");
  if(req.headers.host!==host||(req.headers.origin&&req.headers.origin!=='http://'+host))return json(res,403,{error:'Forbidden origin'});
  const url=new URL(req.url,'http://'+host),p=url.pathname;
  if(req.method==='GET'&&p.startsWith('/api/assets/')){
    const id=p.slice('/api/assets/'.length);
    const found=assetStore.read(id);if(!found)return json(res,404,{error:'Asset not found'});
    res.writeHead(200,{'Content-Type':found.asset.mime_type,'Content-Length':found.buffer.length,'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'});
    return res.end(found.buffer);
  }
  if(req.method==='GET'&&assets.has(p)){
    const [type,file]=assets.get(p);res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store'});return res.end(readFileSync(new URL('../web/'+file,import.meta.url)));
  }
  if(req.method==='GET'&&p==='/api/history'){
    try{
      const around=url.searchParams.get('around');
      if(around){const page=store.historyAround(around,80,'default');if(!page)return json(res,404,{error:'Message not found'});return json(res,200,{...page,pending_growth:growth.getPending('default')});}
      const raw=url.searchParams.get('before'),before=raw===null?null:Number(raw);
      if(raw!==null&&!/^\d+$/.test(raw))return json(res,400,{error:'Invalid history cursor'});
      return json(res,200,{...store.historyPage(80,'default',before),pending_growth:growth.getPending('default')});
    }catch{return json(res,400,{error:'Unable to load history'});}
  }
  if(req.method==='GET'&&p==='/api/search'){
    const q=url.searchParams.get('q')||'',from=url.searchParams.get('from')||null,to=url.searchParams.get('to')||null;
    if(!q.trim()||q.length>120|| (from&&!/^\d{4}-\d{2}-\d{2}$/.test(from)) || (to&&!/^\d{4}-\d{2}-\d{2}$/.test(to)))return json(res,400,{error:'Invalid search query'});
    try{return json(res,200,{results:store.search(q,{from,to,limit:50,conversationId:'default'})});}catch{return json(res,400,{error:'Unable to search history'});}
  }
  if(req.method==='GET'&&p.startsWith('/api/requests/')){
    const id=p.slice('/api/requests/'.length);
    if(!/^[0-9a-f-]{36}$/i.test(id))return json(res,400,{error:'Invalid request ID'});
    return json(res,200,{turn:store.requestTurn(id)||null});
  }
  if(req.method==='GET'&&p==='/api/status'){const instruction=store.getInstructions('default');return json(res,200,{jobs:store.jobCounts(),memoryEnabled:!!memory,conversationId:'default',sessionInstruction:instruction?{active:true,version:instruction.version,characters:Array.from(instruction.content).length}: {active:false}});}
  if(req.method==='GET'&&p==='/api/memories')return json(res,200,{memories:memory?.list()||[]});
  if(req.method==='GET'&&p==='/api/understanding')return json(res,200,{claims:understanding?.list()||[]});
  if(req.method==='GET'&&p==='/api/jobs')return json(res,200,{jobs:store.jobs()});
  if(req.method==='POST'&&p==='/api/chat/stream'){
    if(req.headers.origin!=='http://'+host||!req.headers['content-type']?.startsWith('application/json'))return json(res,403,{error:'Invalid request origin'});
    let input,requestId;
    try{const b=await body(req);input=b.text;requestId=b.request_id;if(typeof input!=='string'||!input.trim()||input.length>16000||typeof requestId!=='string'||!/^[0-9a-f-]{36}$/i.test(requestId))throw Error();}
    catch{return json(res,400,{error:'Invalid input'});}
    const controller=new AbortController();
    res.on('close',()=>{if(!res.writableEnded)controller.abort();});
    req.on('aborted',()=>controller.abort());
    res.writeHead(200,{'Content-Type':'text/event-stream; charset=utf-8','Cache-Control':'no-cache, no-transform','Connection':'keep-alive','X-Accel-Buffering':'no'});
    res.flushHeaders?.();
    try{
      const turn=await agent.replyStream(input,'default',{signal:controller.signal,requestId,onToken:token=>event(res,'token',{text:token})});
      if(!controller.signal.aborted)event(res,'done',{turn});
    }catch(error){
      if(!controller.signal.aborted)event(res,'error',{message:error?.name==='AbortError'?'回复已停止':'暂时无法获取回复，请检查模型服务后重试'});
    }finally{if(!res.writableEnded)res.end();}
    return;
  }
  return json(res,404,{error:'Not found'});
}).listen(port,'127.0.0.1',()=>console.log('Becoming AI friend: http://'+host));
