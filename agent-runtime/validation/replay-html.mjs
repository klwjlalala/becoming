import {readFileSync,writeFileSync,mkdirSync,mkdtempSync,rmSync} from 'node:fs';
import {basename,dirname,resolve,join,sep} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {Gateway,Agent} from '../agent.mjs';
import {Store} from '../store.mjs';
import {GrowthStore,GrowthTools} from '../growth.mjs';
import {CapabilityRegistry} from '../capabilities/registry.mjs';
import {registerDefaultCapabilities} from '../capabilities/defaults.mjs';
import {AssetStore} from '../assets.mjs';
import {parseSource} from './html-replay-parser.mjs';
import {analyzeReplay} from './replay-analysis.mjs';

const sourcePath=process.argv[2];
if(!sourcePath){console.error('Usage: node agent-runtime/validation/replay-html.mjs <conversation.html>');process.exit(2);}
const html=readFileSync(resolve(sourcePath),'utf8'),sourceHash=createHash('sha256').update(html).digest('hex');
const {prompt,userTurns}=parseSource(html);
const output=resolve(process.env.LIFE_MEANING_REPORT||'agent-runtime/artifacts/life-meaning-replay.json');
const assetDir=resolve(process.env.BECOMING_ASSET_DIR||join(dirname(output),'life-meaning-assets'));
const maxModelCalls=Number(process.env.LIFE_MEANING_MAX_CALLS||40);
const maxImageCalls=Number(process.env.LIFE_MEANING_MAX_IMAGE_CALLS||2);
if(!Number.isInteger(maxModelCalls)||maxModelCalls<13||maxModelCalls>100)throw Error('LIFE_MEANING_MAX_CALLS must be an integer from 13 to 100');
if(!Number.isInteger(maxImageCalls)||maxImageCalls<0||maxImageCalls>4)throw Error('LIFE_MEANING_MAX_IMAGE_CALLS must be an integer from 0 to 4');

class ReplayGateway extends Gateway{
  constructor(url){super(url);this.calls=0;this.imageCalls=0;this.trace=[];this.imageTrace=[];}
  async capture(method,messages,options,invoke){
    if(this.calls>=maxModelCalls)throw Error('HTML replay model-call budget exhausted');
    const call=++this.calls,started=performance.now(),lastUser=messages.filter(message=>message.role==='user').at(-1)?.content||'';
    try{
      const response=await invoke();
      this.trace.push({
        call,method,elapsed_ms:Math.round(performance.now()-started),
        input_characters:messages.reduce((sum,message)=>sum+String(message.content||'').length,0),
        last_user_input_characters:Array.from(lastUser).length,
        system_contains_prompt:String(messages[0]?.content||'').includes(prompt),
        available_tools:(options.tools||[]).map(tool=>tool.function?.name).filter(Boolean),
        tool_calls:(response.tool_calls||[]).map(tool=>({name:tool.function.name,arguments_characters:tool.function.arguments.length})),
        response_text_characters:Array.from(response.text||'').length,usage:response.usage||null
      });
      return response;
    }catch(error){
      this.trace.push({call,method,elapsed_ms:Math.round(performance.now()-started),last_user_input_characters:Array.from(lastUser).length,error:error.message});
      throw error;
    }
  }
  streamStructured(messages,options={}){return this.capture('streamStructured',messages,options,()=>super.streamStructured(messages,options));}
  completeStructured(messages,options={}){return this.capture('completeStructured',messages,options,()=>super.completeStructured(messages,options));}
  async generateImage(options={}){
    if(this.imageCalls>=maxImageCalls)throw Error('HTML replay image-generation budget exhausted');
    const call=++this.imageCalls,started=performance.now();
    try{
      const result=await super.generateImage(options);
      this.imageTrace.push({call,elapsed_ms:Math.round(performance.now()-started),prompt_characters:Array.from(options.prompt||'').length,size:options.size||'1024x1024',mime_type:result.mime_type,size_bytes:result.buffer.length,status:'completed'});
      return result;
    }catch(error){
      this.imageTrace.push({call,elapsed_ms:Math.round(performance.now()-started),prompt_characters:Array.from(options.prompt||'').length,size:options.size||'1024x1024',status:'failed',error:error.message});
      throw error;
    }
  }
}

const tempDir=mkdtempSync(join(tmpdir(),'becoming-html-replay-'));
const dbPath=join(tempDir,'replay.sqlite3');
let store=new Store(dbPath);
const growthStore=new GrowthStore(':memory:');
const gateway=new ReplayGateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000');
let assetStore=new AssetStore(store,assetDir);
const growth=new GrowthTools(gateway,growthStore);
const imageEnabled=process.env.BECOMING_ENABLE_IMAGE_GENERATION==='1';
const registry=registerDefaultCapabilities({registry:new CapabilityRegistry(),growth,gateway,assetStore,enableImage:imageEnabled});
const agent=new Agent(store,gateway,{growth,capabilities:registry,historyTurns:12});
const report={
  test:'local-html-transcript-replay',source_file:basename(sourcePath),source_sha256:sourceHash,
  replay_mode:'original-user-turns-only; original assistant responses are intentionally excluded',
  prompt_characters:Array.from(prompt).length,user_turn_count:userTurns.length,history_window:12,
  image_generation_enabled:imageEnabled,max_model_calls:maxModelCalls,max_image_calls:maxImageCalls,
  started_at:new Date().toISOString(),database_restart_verified:false,turns:[],checks:{},
  summary:{model_calls:0,image_generation_calls:0,tool_calls:0,images:0,charts:0,diagrams:0,failed_tools:0}
};
function save(){
  if(store)report.assets=store.db.prepare('SELECT id,file_name,mime_type,size_bytes,created_at FROM assets ORDER BY created_at').all();
  report.summary.model_calls=gateway.calls;
  report.summary.image_generation_calls=gateway.imageCalls;
  report.trace=gateway.trace;
  report.image_trace=gateway.imageTrace;
  report.summary.tool_calls=report.turns.reduce((sum,turn)=>sum+(turn.event?.capabilities?.length||0),0);
  report.summary.images=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='image').length,0);
  report.summary.charts=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='chart').length,0);
  report.summary.diagrams=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='diagram').length,0);
  report.summary.failed_tools=report.turns.reduce((sum,turn)=>sum+(turn.event?.capabilities||[]).filter(event=>event.status==='failed').length,0);
  mkdirSync(dirname(output),{recursive:true});writeFileSync(output,JSON.stringify(report,null,2)+'\n');
}
function check(name,passed,detail=null){report.checks[name]={passed:!!passed,...(detail===null?{}:{detail})};}
try{
  const first=await agent.reply(prompt,'default');
  report.session_instruction=first.event?.session_instruction??null;
  report.turns.push({index:0,turn_id:first.id,kind:'initial_instruction',user:'[Full custom instruction supplied from local HTML]',assistant:first.assistant,content_blocks:first.content_blocks||[],event:first.event,pending_growth:!!first.pending_growth});
  save();
  for(let i=0;i<userTurns.length;i++){
    const turn=await agent.reply(userTurns[i],'default');
    report.turns.push({index:i+1,turn_id:turn.id,kind:'replayed_user_turn',user:userTurns[i],assistant:turn.assistant,content_blocks:turn.content_blocks||[],event:turn.event,pending_growth:!!turn.pending_growth});
    save();
    console.log('Completed replay turn '+(i+1)+'/'+userTurns.length+'; content blocks: '+(turn.content_blocks||[]).length);
  }

  // Reopen the SQLite database and asset index to verify persistence across a process restart.
  store.close();store=null;
  store=new Store(dbPath);assetStore=new AssetStore(store,assetDir);report.database_restart_verified=true;

  const firstAnswer=report.turns[0]?.assistant||'';
  const analysis=analyzeReplay(report.turns);
  const handbookTurn=report.turns.find(turn=>turn.index===analysis.handbook_turn_index)||null;
  const final=handbookTurn?.assistant||'';
  const compactFinal=analysis.handbook_characters_without_whitespace;
  const history=store.history(200,'default'),recentHistory=store.history(12,'default');
  const imageBlocks=report.turns.flatMap(turn=>turn.content_blocks||[]).filter(block=>block.type==='image');
  const invalidAssets=imageBlocks.filter(block=>!block.asset_id||!assetStore.read(block.asset_id));
  const missingPersistedBlocks=report.turns.filter(turn=>{
    const saved=store.turn(turn.turn_id);
    return !saved||JSON.stringify(saved.content_blocks||[])!==JSON.stringify(turn.content_blocks||[]);
  });
  const instructions=store.getInstructions('default');
  const questionMarks=(firstAnswer.match(/[？?]/g)||[]).length;

  check('initial_prompt_pinned',report.session_instruction?.status==='pinned',report.session_instruction||null);
  check('first_response_has_warm_introduction',/人生意义设计课|人生设计课程/.test(firstAnswer));
  check('first_response_marks_stage_1_of_4',/进度\s*1\s*\/\s*4/.test(firstAnswer));
  check('first_response_keeps_question_flow',questionMarks>=1&&questionMarks<=3,{question_marks:questionMarks});
  check('all_user_turns_replayed',report.turns.length===userTurns.length+1,{expected:userTurns.length,actual:report.turns.length});
  check('all_user_turns_preserved_in_order',history.slice(-userTurns.length).every((turn,index)=>turn.user===userTurns[index]));
  check('prompt_remains_active_after_history_window',instructions?.content===prompt&&(!recentHistory.some(turn=>turn.user===prompt)||userTurns.length<12));
  for(const [name,result] of Object.entries(analysis.checks))check(name,result.passed,result.detail??null);
  check('no_tool_execution_failures',report.summary.failed_tools===0,{failed_tools:report.summary.failed_tools});
  check('image_capability_matches_configuration',imageEnabled?registry.has('image_generate'):!registry.has('image_generate'));
  check('all_generated_images_are_valid_local_assets',invalidAssets.length===0,{image_blocks:imageBlocks.length,invalid_asset_ids:invalidAssets.map(block=>block.asset_id||null)});
  check('content_blocks_survive_sqlite_restart',missingPersistedBlocks.length===0,{missing_turn_ids:missingPersistedBlocks.map(turn=>turn.turn_id)});
  check('image_assets_survive_sqlite_restart',invalidAssets.length===0,{verified_images:imageBlocks.length});
  check('model_call_budget_respected',gateway.calls<=maxModelCalls,{model_calls:gateway.calls,max_model_calls:maxModelCalls});
  check('image_generation_budget_respected',gateway.imageCalls<=maxImageCalls,{image_generation_calls:gateway.imageCalls,max_image_calls:maxImageCalls});
  check('no_unconfirmed_growth_mutations',report.turns.every(turn=>!turn.pending_growth));

  report.finished_at=new Date().toISOString();
  report.handbook=analysis;
  report.final_answer_characters=Array.from(final).length;
  report.final_characters_without_whitespace=compactFinal;
  report.final_table_lines=analysis.handbook_table_lines;
  report.missing_sections=analysis.handbook_missing_sections;
  report.final_ending_excerpt=analysis.handbook_ending_excerpt;
  report.last_turn_response_characters=analysis.final_turn_response_characters;
  report.instruction_remained_active=!!instructions;
  report.visual_diagnostic=imageEnabled?(imageBlocks.length?'image_generation_used':'image_generation_enabled_but_not_selected'):'image_generation_disabled';
  report.status=Object.values(report.checks).every(item=>item.passed)?'passed':'needs_review';
  save();
  console.log(JSON.stringify({status:report.status,turns:userTurns.length,summary:report.summary,handbook_characters_without_whitespace:compactFinal,handbook_turn_index:analysis.handbook_turn_index,latest_substantive_user_turn_index:analysis.latest_substantive_user_turn_index,checks:report.checks,report:output,assets:assetDir},null,2));
  if(report.status!=='passed')process.exitCode=1;
}catch(error){
  report.status='failed';report.error=error.message;report.finished_at=new Date().toISOString();
  try{save();}catch{}
  console.error(JSON.stringify({status:'failed',error:error.message,summary:report.summary,report:output}));
  process.exitCode=1;
}finally{
  try{save();}catch{}
  try{growthStore.close();}catch{}
  try{store?.close();}catch{}
  if(assetDir!==tempDir&&!assetDir.startsWith(tempDir+sep))rmSync(tempDir,{recursive:true,force:true});
  console.log(JSON.stringify({status:report.status,turns:report.turns.length,summary:report.summary,final_answer_characters:report.final_answer_characters,report:output,assets:assetDir,database_restart_verified:report.database_restart_verified},null,2));
}
