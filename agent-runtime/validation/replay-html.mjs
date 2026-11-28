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
  history_window:12,
  image_generation_enabled:process.env.BECOMING_ENABLE_IMAGE_GENERATION==='1',
  started_at:new Date().toISOString(),
  turns:[],
  checks:{},
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
function check(name,passed,detail=null){
  report.checks[name]={passed:!!passed,...(detail===null?{}:{detail})};
}
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

  const firstAnswer=report.turns[0]?.assistant||'';
  const final=report.turns.at(-1)?.assistant||'';
  const compactFinal=Array.from(final.replace(/\s/g,'')).length;
  const sectionPatterns=[
    ['你在这里',/你在这里/],
    ['你早就拥有的意义',/你早就拥有的意义|早已拥有的意义/],
    ['被你忽略的部分',/被你忽略的部分|你可能忽略的部分/],
    ['你的人生罗盘',/你的人生罗盘|人生罗盘/],
    ['设计更多意义时刻',/设计更多意义时刻|亲手设计更多|更多有意义的时刻/],
    ['带着问题生活',/带着问题生活/],
    ['陪你一起变好的人',/陪你一起变好的人|一起变好的人/],
    ['你的人生季节',/你的人生季节|人生季节/]
  ];
  const missingSections=sectionPatterns.filter(([,pattern])=>!pattern.test(final)).map(([name])=>name);
  const tableLines=final.split('\n').filter(line=>/^\s*\|.*\|\s*$/.test(line));
  const ending=final.trim().slice(-500);
  const history=store.history(200,'default');
  const recentHistory=store.history(12,'default');
  const imageBlocks=report.turns.flatMap(turn=>turn.content_blocks||[]).filter(block=>block.type==='image');
  const invalidAssets=imageBlocks.filter(block=>!block.asset_id||!assetStore.read(block.asset_id));
  const missingPersistedBlocks=report.turns.filter(turn=>{
    const saved=store.turn(turn.turn_id);
    return !saved||JSON.stringify(saved.content_blocks||[])!==JSON.stringify(turn.content_blocks||[]);
  });
  const instructions=store.getInstructions('default');

  check('initial_prompt_pinned',report.session_instruction?.status==='pinned',report.session_instruction||null);
  check('first_response_has_warm_introduction',/人生意义设计课|人生设计课程/.test(firstAnswer));
  check('first_response_marks_stage_1_of_4',/进度\s*1\s*\/\s*4/.test(firstAnswer));
  const questionMarks=(firstAnswer.match(/[？?]/g)||[]).length;
  check('first_response_keeps_question_flow',questionMarks>=1&&questionMarks<=3,{question_marks:questionMarks});
  check('all_user_turns_replayed',report.turns.length===userTurns.length+1,{expected:userTurns.length,actual:report.turns.length});
  check('all_user_turns_preserved_in_order',history.slice(-userTurns.length).every((turn,index)=>turn.user===userTurns[index]));
  check('prompt_remains_active_after_history_window',instructions?.content===prompt&&(!recentHistory.some(turn=>turn.user===prompt)||userTurns.length<12));
  check('final_response_is_personal_meaning_handbook',/个人意义设计手册/.test(final));
  check('final_response_length_5000_to_7000_characters',compactFinal>=5000&&compactFinal<=7000,{characters_without_whitespace:compactFinal});
  check('final_response_covers_all_eight_named_sections',missingSections.length===0,{missing_sections:missingSections});
  check('final_response_has_reflective_closing',ending.length>=100&&/意义|时刻|生活|未来|山|风|树|开始|继续/.test(ending),{ending_excerpt:ending.slice(-180)});
  check('final_response_uses_markdown_tables',tableLines.length>=4,{table_lines:tableLines.length});
  check('no_tool_execution_failures',report.summary.failed_tools===0,{failed_tools:report.summary.failed_tools});
  check('all_generated_images_are_valid_local_assets',invalidAssets.length===0,{invalid_asset_ids:invalidAssets.map(block=>block.asset_id||null)});
  check('content_blocks_survive_history_reload',missingPersistedBlocks.length===0,{missing_turn_ids:missingPersistedBlocks.map(turn=>turn.turn_id)});
  check('no_unconfirmed_growth_mutations',report.turns.every(turn=>!turn.pending_growth));
  report.finished_at=new Date().toISOString();
  report.final_answer_characters=Array.from(final).length;
  report.final_characters_without_whitespace=compactFinal;
  report.final_table_lines=tableLines.length;
  report.missing_sections=missingSections;
  report.final_ending_excerpt=ending.slice(-180);
  report.instruction_remained_active=!!instructions;
  report.status=Object.values(report.checks).every(item=>item.passed)?'passed':'needs_review';
  save();
  console.log(JSON.stringify({status:report.status,turns:userTurns.length,summary:report.summary,final_characters_without_whitespace:compactFinal,checks:report.checks,report:output,assets:assetDir},null,2));
  if(report.status!=='passed')process.exitCode=1;
}catch(error){
  report.status='failed';report.error=error.message;report.finished_at=new Date().toISOString();process.exitCode=1;
}finally{
  save();growthStore.close();store.close();
  console.log(JSON.stringify({status:report.status,turns:report.turns.length,summary:report.summary,final_answer_characters:report.final_answer_characters,report:output,assets:assetDir},null,2));
}
