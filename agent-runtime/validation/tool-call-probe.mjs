import {mkdirSync,writeFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {Gateway} from '../agent.mjs';
import {CapabilityRegistry,runCapabilityLoop} from '../capabilities/registry.mjs';
import {registerDefaultCapabilities} from '../capabilities/defaults.mjs';

const output=resolve(process.env.TOOL_CALL_REPORT||'agent-runtime/artifacts/tool-call-probe.json');
const report={test:'native-function-tool-call-and-discovery-probe',model_calls:0,provider_response:null};
const model=new Gateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000');
let modelCalls=0;for(const method of ['completeStructured','streamStructured']){const original=model[method].bind(model);model[method]=async(...args)=>{modelCalls++;return original(...args);};}
const tool={type:'function',function:{
  name:'record_test_result',
  description:'Record a successful tool-call capability probe. Call this exactly once when asked.',
  parameters:{
    type:'object',
    properties:{value:{type:'string',enum:['tool-call-ok']}},
    required:['value'],
    additionalProperties:false
  }
}};
try{
  const response=await model.completeStructured([
    {role:'system',content:'You are testing native function calling. You must call the provided function exactly once with value set to tool-call-ok. Do not answer in plain text and do not invent another tool.'},
    {role:'user',content:'Call record_test_result now with the required value.'}
  ],{tools:[tool],tool_choice:{type:'function',function:{name:'record_test_result'}}});
  report.provider_response=response;
  const calls=response.tool_calls;
  if(!Array.isArray(calls)||calls.length!==1)throw Error('Provider did not return exactly one native tool call');
  const call=calls[0],args=JSON.parse(call.function.arguments);
  if(call.function.name!=='record_test_result'||args.value!=='tool-call-ok')throw Error('Provider returned an unexpected function name or arguments');
  report.checks={native_tool_call:true,forced_tool_choice:true,arguments_valid:true};
  const registry=registerDefaultCapabilities({registry:new CapabilityRegistry(),enableImage:false});
  const chart=await runCapabilityLoop(model,[
    {role:'system',content:'You can discover tools with discover_capabilities. The user asks for a chart. Discover the relevant capability, call it with the user data, and then briefly report completion.'},
    {role:'user',content:'请把下面数据制作成柱状图：一月 2，二月 4，三月 7。标题为每月阅读量。'}
  ],registry,{maxRounds:5,maxCalls:4});
  if(!chart.blocks.some(block=>block.type==='chart'&&block.chartType==='bar'))throw Error('The model did not discover and execute the chart capability');
  report.chart_test={answer:chart.answer,events:chart.events,blocks:chart.blocks};
  report.checks.capability_discovery=true;
  report.checks.chart_tool_executed=true;
  const diagram=await runCapabilityLoop(model,[
    {role:'system',content:'You can discover tools with discover_capabilities. The user asks for a relationship diagram. Discover the relevant capability, call it with the requested relationships, then briefly report completion.'},
    {role:'user',content:'请制作一张横向关系图，展示“好奇心 → 探索 → 创造 → 帮助他人”的关系。请为每个节点写一句简短说明，并连接相邻节点。'}
  ],registry,{maxRounds:5,maxCalls:4});
  const diagramEvent=diagram.events.find(event=>event.name==='diagram_create'&&event.status==='completed');
  if(!diagramEvent||!diagram.blocks.some(block=>block.type==='diagram'&&block.nodes?.length>=2&&block.edges?.length>=1))throw Error('The model did not discover and execute the diagram capability');
  report.diagram_test={answer:diagram.answer,events:diagram.events,blocks:diagram.blocks};
  report.checks.diagram_capability_discovery=diagram.events.some(event=>event.name==='discover_capabilities'&&event.status==='completed');
  report.checks.diagram_tool_executed=!!diagramEvent;
  report.status='supported';
}catch(error){
  report.status='unsupported_or_incompatible';
  report.error=error.message;
  process.exitCode=1;
}finally{
  report.model_calls=modelCalls;
  mkdirSync(dirname(output),{recursive:true});
  writeFileSync(output,JSON.stringify(report,null,2)+'\n');
  report.model_calls=modelCalls;
  console.log(JSON.stringify(report,null,2));
}
