import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {basename,dirname,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {Gateway,Agent} from '../agent.mjs';
import {Store} from '../store.mjs';
import {GrowthStore,GrowthTools} from '../growth.mjs';
import {CapabilityRegistry} from '../capabilities/registry.mjs';
import {registerDefaultCapabilities} from '../capabilities/defaults.mjs';
import {AssetStore} from '../assets.mjs';
import {parseSource} from './html-replay-parser.mjs';

const sourcePath=process.argv[2];
if(!sourcePath){console.error('Usage: node agent-runtime/validation/replay-html.mjs <conversation.html>');process.exit(2);}
const html=readFileSync(resolve(sourcePath),'utf8'),sourceHash=createHash('sha256').update(html).digest('hex');
const {prompt,userTurns}=parseSource(html);
const output=resolve(process.env.LIFE_MEANING_REPORT||'agent-runtime/artifacts/life-meaning-replay.json');
const assetDir=resolve(process.env.BECOMING_ASSET_DIR||dirname(output)+'/life-meaning-assets');
const store=new Store(':memory:'),growthStore=new GrowthStore(':memory:'),gateway=new Gateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000');
const assetStore=new AssetStore(store,assetDir),growth=new GrowthTools(gateway,growthStore),registry=registerDefaultCapabilities({
  registry:new CapabilityRegistry(),growth,gateway,assetStore,enableImage:process.env.BECOMING_ENABLE_IMAGE_GENERATION==='1'
});
const agent=new Agent(store,gateway,{growth,capabilities:registry,historyTurns:12});
const report={
  test:'local-html-transcript-replay',
  source_file:basename(sourcePath),
  source_sha256:sourceHash,
  replay_mode:'original-user-turns-only; original assistant responses are intentionally excluded',
  prompt_characters:Array.from(prompt).length,
  user_turn_count:userTurns.length,
  image_generation_enabled:process.env.BECOMING_ENABLE_IMAGE_GENERATION==='1',
  started_at:new Date().toISOString(),
  turns:[],
  summary:{tool_calls:0,images:0,charts:0,diagrams:0,failed_tools:0}
};
function save(){
  const assets=store.db.prepare('SELECT id,file_name,mime_type,size_bytes,created_at FROM assets ORDER BY created_at').all();
  report.assets=assets;
  report.summary.tool_calls=report.turns.reduce((sum,turn)=>sum+(turn.event?.capabilities?.length||0),0);
  report.summary.images=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='image').length,0);
  report.summary.charts=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='chart').length,0);
  report.summary.diagrams=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='diagram').length,0);
  report.summary.failed_tools=report.turns.reduce((sum,turn)=>sum+(turn.event?.capabilities||[]).filter(event=>event.status==='failed').length,0);
  mkdirSync(dirname(output),{recursive:true});writeFileSync(output,JSON.stringify(report,null,2)+'\n');
}
try{
  const first=await agent.reply(prompt,'default');
  report.session_instruction=first.event?.session_instruction??null;
  report.turns.push({index:0,kind:'initial_instruction',user:'[Full custom instruction supplied from local HTML]',assistant:first.assistant,content_blocks:first.content_blocks||[],event:first.event,pending_growth:!!first.pending_growth});
  save();
  for(let i=0;i<userTurns.length;i++){
    const turn=await agent.reply(userTurns[i],'default');
    report.turns.push({index:i+1,kind:'replayed_user_turn',user:userTurns[i],assistant:turn.assistant,content_blocks:turn.content_blocks||[],event:turn.event,pending_growth:!!turn.pending_growth});
    save();
    console.log('Completed replay turn '+(i+1)+'/'+userTurns.length+'; content blocks: '+(turn.content_blocks||[]).length);
  }
  report.finished_at=new Date().toISOString();
  report.final_answer_characters=Array.from(report.turns.at(-1)?.assistant||'').length;
  report.instruction_remained_active=!!agent.store.getInstructions('default');
  report.status='completed';
}catch(error){
  report.status='failed';report.error=error.message;report.finished_at=new Date().toISOString();process.exitCode=1;
}finally{
  save();growthStore.close();store.close();
  console.log(JSON.stringify({status:report.status,turns:report.turns.length,summary:report.summary,final_answer_characters:report.final_answer_characters,report:output,assets:assetDir},null,2));
}
