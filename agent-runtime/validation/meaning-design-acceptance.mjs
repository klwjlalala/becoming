import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {Gateway,Agent} from '../agent.mjs';
import {Store} from '../store.mjs';
import {CapabilityRegistry} from '../capabilities/registry.mjs';
import {registerDefaultCapabilities} from '../capabilities/defaults.mjs';
import {AssetStore} from '../assets.mjs';
import {analyzeReplay} from './replay-analysis.mjs';

const fixture=JSON.parse(readFileSync(new URL('./fixtures/meaning-design-dialogue.json',import.meta.url),'utf8'));
const prompt=readFileSync(new URL('./fixtures/meaning-design-prompt.txt',import.meta.url),'utf8').trim();
const maxCalls=Number(process.env.MEANING_DESIGN_MAX_CALLS||24);
if(!Number.isInteger(maxCalls)||maxCalls<13||maxCalls>40)throw Error('Invalid meaning-design model-call budget');
const output=resolve(process.env.MEANING_DESIGN_REPORT||'artifacts/meaning-design-agent-acceptance.json');
const assetDir=resolve(process.env.BECOMING_ASSET_DIR||dirname(output)+'/meaning-design-assets');

class BudgetedGateway extends Gateway{
  constructor(url,limit,instruction){
    super(url);this.limit=limit;this.instruction=instruction;this.calls=0;this.trace=[];
  }
  async capture(method,messages,options,invoke){
    if(this.calls>=this.limit)throw Error('Meaning-design evaluation model-call budget exhausted');
    const call=++this.calls,started=performance.now();
    try{
      const response=await invoke();
      this.trace.push({
        call,method,
        elapsed_ms:Math.round(performance.now()-started),
        input_characters:messages.reduce((sum,message)=>sum+String(message.content||'').length,0),
        last_user_input:messages.filter(message=>message.role==='user').at(-1)?.content||'',
        system_contains_prompt:String(messages[0]?.content||'').includes(this.instruction),
        available_tools:(options.tools||[]).map(tool=>tool.function?.name).filter(Boolean),
        tool_calls:(response.tool_calls||[]).map(tool=>({name:tool.function.name,arguments:tool.function.arguments})),
        response_text:response.text||'',
        usage:response.usage||null
      });
      return response;
    }catch(error){
      this.trace.push({call,method,elapsed_ms:Math.round(performance.now()-started),error:error.message,last_user_input:messages.filter(message=>message.role==='user').at(-1)?.content||''});
      throw error;
    }
  }
  streamStructured(messages,options={}){return this.capture('streamStructured',messages,options,()=>super.streamStructured(messages,options));}
  completeStructured(messages,options={}){return this.capture('completeStructured',messages,options,()=>super.completeStructured(messages,options));}
}

const store=new Store(':memory:');
const gateway=new BudgetedGateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000',maxCalls,prompt);
const assetStore=new AssetStore(store,assetDir);
const registry=registerDefaultCapabilities({registry:new CapabilityRegistry(),gateway,assetStore,enableImage:false});
const agent=new Agent(store,gateway,{capabilities:registry,historyTurns:12});
const report={
  test:'meaning-design-prompt-with-general-agent-capabilities',
  fictional_data_only:fixture.fictional_data_only===true,
  fixture:fixture.fixture,
  prompt_characters:Array.from(prompt).length,
  planned_user_answers:fixture.answers.length,
  history_window:12,
  image_generation_enabled:false,
  turns:[],
  checks:{},
  summary:{model_calls:0,tool_calls:0,failed_tools:0,images:0,charts:0,diagrams:0}
};

function save(){
  report.summary.model_calls=gateway.calls;
  report.trace=gateway.trace;
  report.summary.tool_calls=report.turns.reduce((sum,turn)=>sum+(turn.event?.capabilities?.length||0),0);
  report.summary.failed_tools=report.turns.reduce((sum,turn)=>sum+(turn.event?.capabilities||[]).filter(event=>event.status==='failed').length,0);
  report.summary.images=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='image').length,0);
  report.summary.charts=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='chart').length,0);
  report.summary.diagrams=report.turns.reduce((sum,turn)=>sum+(turn.content_blocks||[]).filter(block=>block.type==='diagram').length,0);
  mkdirSync(dirname(output),{recursive:true});
  writeFileSync(output,JSON.stringify(report,null,2)+'\n');
}
function check(name,passed,detail=null){
  report.checks[name]={passed:!!passed,...(detail===null?{}:{detail})};
}

try{
  if(fixture.fictional_data_only!==true)throw Error('Acceptance fixture must contain fictional data only');
  if(!Array.isArray(fixture.answers)||fixture.answers.length!==12)throw Error('Expected the complete 12-answer dialogue fixture');
  if(prompt.length<2000)throw Error('Prompt fixture is unexpectedly short');

  const first=await agent.reply(prompt,'default');
  report.turns.push({index:0,kind:'initial_instruction',assistant:first.assistant,content_blocks:first.content_blocks||[],event:first.event});
  if(first.event?.session_instruction?.status!=='pinned')throw Error('The initial prompt was not pinned as a session instruction');
  save();

  for(let i=0;i<fixture.answers.length;i++){
    const turn=await agent.reply(fixture.answers[i],'default');
    report.turns.push({index:i+1,kind:'replayed_user_turn',user:fixture.answers[i],assistant:turn.assistant,content_blocks:turn.content_blocks||[],event:turn.event,pending_growth:!!turn.pending_growth});
    save();
    console.log('Meaning-design turn '+(i+1)+'/'+fixture.answers.length+' completed.');
  }

  const firstAnswer=report.turns[0].assistant||'';
  const analysis=analyzeReplay(report.turns);
  const handbookTurn=report.turns.find(turn=>turn.index===analysis.handbook_turn_index)||null;
  const final=handbookTurn?.assistant||'';
  const compactFinal=analysis.handbook_characters_without_whitespace;
  const missingSections=analysis.handbook_missing_sections;
  const ending=analysis.handbook_ending_excerpt;
  const questionMarks=(firstAnswer.match(/[？?]/g)||[]).length;
  const lastModelCall=[...gateway.trace].reverse().find(call=>call.last_user_input===fixture.answers.at(-1));
  const history=store.history(12,'default');
  const events=report.turns.flatMap(turn=>turn.event?.capabilities||[]);
  const themeChecks=[
    ['AI探索兴趣',/AI|人工智能/.test(final)],
    ['游戏或智能体创造兴趣',/游戏|智能体|协同机制/.test(final)],
    ['山顶与城市体验',/山顶|山上|城市/.test(final)],
    ['自由与自主权',/自由|自主/.test(final)],
    ['帮助他人',/帮助他人|帮助别人|让别人/.test(final)],
    ['小屋与安静生活',/小屋|阳台|晒太阳|安静/.test(final)]
  ];

  check('initial_prompt_pinned',first.event?.session_instruction?.status==='pinned',first.event?.session_instruction||null);
  check('first_response_has_warm_introduction',/人生意义设计课|人生设计课程/.test(firstAnswer));
  check('first_response_marks_stage_1_of_4',/进度\s*1\s*\/\s*4/.test(firstAnswer));
  check('first_response_starts_with_one_question',questionMarks>=1&&questionMarks<=3,{question_marks:questionMarks});
  check('all_12_user_answers_replayed',report.turns.length===fixture.answers.length+1&&history.length===12);
  check('all_user_answers_preserved_in_order',history.every((turn,index)=>turn.user===fixture.answers[index]));
  check('prompt_survives_history_window_rollover',!history.some(turn=>turn.user===prompt)&&!!lastModelCall?.system_contains_prompt);
  for(const [name,result] of Object.entries(analysis.checks))check(name,result.passed,result.detail??null);
  check('final_response_is_personal_meaning_handbook',/个人意义设计手册/.test(final));
  check('final_response_length_5000_to_7000_characters',compactFinal>=5000&&compactFinal<=7000,{characters_without_whitespace:compactFinal});
  check('final_response_covers_all_eight_named_sections',missingSections.length===0,{missing_sections:missingSections});
  check('final_response_has_reflective_closing',ending.length>=100&&/意义|时刻|生活|未来|山|风|树|开始|继续/.test(ending),{ending_excerpt:ending.slice(-180)});
  check('final_response_uses_markdown_tables',analysis.handbook_table_lines>=4,{table_lines:analysis.handbook_table_lines});
  check('final_response_reflects_fixture_evidence',themeChecks.every(([,passed])=>passed),{themes:themeChecks.map(([name,passed])=>({name,passed}))});
  check('no_tool_execution_failures',report.summary.failed_tools===0,{failed_tools:report.summary.failed_tools});
  check('no_unconfirmed_growth_mutations',report.turns.every(turn=>!turn.pending_growth));
  const revisionConversation=store.createConversation('artifact-revision').id;
  const revisionRequest='请为一位零基础成人制定一份为期3天的 JavaScript 入门学习计划，每天只有30分钟。每一天都要写清学习目标、具体练习和验收标准。';
  const revisionDraft=await agent.reply(revisionRequest,revisionConversation);
  const revisionInput='补充一个重要情况：我已经掌握 HTML 和 CSS，但没有 JavaScript 经验；另外我只能使用手机学习，没有电脑。每天30分钟这个条件不变。';
  const revisionTurn=await agent.reply(revisionInput,revisionConversation);
  const revisedPlan=revisionTurn.assistant||'';
  const revisionChecks={
    substantive_revision:{passed:Array.from(revisedPlan).length>=350,detail:{characters:Array.from(revisedPlan).length}},
    retains_three_day_structure:{passed:/第一天|第1天|Day\s*1/i.test(revisedPlan)&&/第二天|第2天|Day\s*2/i.test(revisedPlan)&&/第三天|第3天|Day\s*3/i.test(revisedPlan)},
    adapts_to_mobile_only_constraint:{passed:/手机|移动端|手机端/.test(revisedPlan)},
    preserves_daily_time_limit:{passed:/30\s*分钟|30分钟|半小时/.test(revisedPlan)},
    uses_existing_html_css_knowledge:{passed:/HTML|CSS/.test(revisedPlan)},
    includes_actionable_practice:{passed:/练习|实践|操作|编写/.test(revisedPlan)}
  };
  report.artifact_revision={
    conversation_id:revisionConversation,
    initial_request:revisionRequest,
    initial_draft_characters:Array.from(revisionDraft.assistant||'').length,
    follow_up:revisionInput,
    updated_response:revisedPlan,
    checks:revisionChecks
  };
  for(const [name,result] of Object.entries(revisionChecks))check('artifact_revision_'+name,result.passed,result.detail??null);
  check('model_call_budget_respected',gateway.calls<=maxCalls,{model_calls:gateway.calls,max_calls:maxCalls});


  report.handbook_analysis=analysis;
  report.final_characters_without_whitespace=compactFinal;
  report.missing_sections=missingSections;
  report.final_table_lines=analysis.handbook_table_lines;
  report.final_ending_excerpt=ending.slice(-180);
  report.final_response=final;
  report.summary.model_calls=gateway.calls;
  report.summary.tool_calls=report.turns.reduce((sum,turn)=>sum+(turn.event?.capabilities?.length||0),0);
  report.summary.failed_tools=report.turns.reduce((sum,turn)=>sum+(turn.event?.capabilities||[]).filter(event=>event.status==='failed').length,0);
  report.status=Object.values(report.checks).every(item=>item.passed)?'passed':'needs_review';
  save();
  console.log(JSON.stringify({status:report.status,model_calls:gateway.calls,max_calls:maxCalls,turns:fixture.answers.length,final_characters_without_whitespace:compactFinal,checks:report.checks,report:output},null,2));
  if(report.status!=='passed')process.exitCode=1;
}catch(error){
  report.status='failed';report.error=error.message;
  save();
  console.error(JSON.stringify({status:'failed',error:error.message,model_calls:gateway.calls,report:output}));
  process.exitCode=1;
}finally{
  store.close();
}
