import {createServer} from 'node:http';
import {readFileSync,mkdirSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {Store} from './store.mjs';
import {Agent,Gateway,SyncWorker} from './agent.mjs';
const port=Number(process.env.BECOMING_LOCAL_PORT||4310);
const host='127.0.0.1:'+port;
const account=process.env.BECOMING_ACCOUNT||'dev';
if(!/^[a-zA-Z0-9_-]{1,64}$/.test(account)) throw Error('Invalid account namespace');
const path=resolve(process.env.BECOMING_LOCAL_DB||'data/local-'+account+'.sqlite3');
mkdirSync(dirname(path),{recursive:true});
const store=new Store(path);
const gateway=new Gateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000',process.env.BECOMING_TOKEN);
const agent=new Agent(store,gateway);
const worker=new SyncWorker(store,gateway);
const enabled=process.env.BECOMING_SYNC==='1';
if(enabled){setInterval(()=>worker.tick(),5000).unref();void worker.tick();}
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
  const p=req.url;
  if(req.method==='GET'&&assets.has(p)){
    const [type,file]=assets.get(p);res.writeHead(200,{'Content-Type':type,'Cache-Control':'no-store'});return res.end(readFileSync(new URL('../web/'+file,import.meta.url)));
  }
  if(req.method==='GET'&&p==='/api/history')return json(res,200,{turns:store.history(200)});
  if(req.method==='GET'&&p==='/api/status')return json(res,200,{syncEnabled:enabled,pending:store.pending().length,lastSuccess:worker.lastSuccess,lastError:worker.lastError});
  if(req.method==='POST'&&p==='/api/chat'){
    if(req.headers.origin!=='http://'+host||!req.headers['content-type']?.startsWith('application/json'))return json(res,403,{error:'Invalid request origin'});
    let input;try{input=(await body(req)).text;if(typeof input!=='string'||!input.trim()||input.length>16000)throw Error();}
    catch{return json(res,400,{error:'Invalid input'});}
    try{return json(res,200,{turn:await agent.reply(input)});}
    catch{return json(res,502,{error:'Agent request failed; no incomplete turn saved'});}
  }
  return json(res,404,{error:'Not found'});
}).listen(port,'127.0.0.1',()=>console.log('Becoming local runtime: http://'+host));
