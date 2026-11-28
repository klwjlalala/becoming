import {mkdirSync,writeFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {Gateway} from '../agent.mjs';
import {CapabilityRegistry,runCapabilityLoop} from '../capabilities/registry.mjs';

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
  const registry=new CapabilityRegistry();
  registry.register({
    name:'chart_create',
    description:'Create a visual chart from structured data. Supports bar, line and pie charts.',
    category:'visualization',
    keywords:['图表','chart','可视化'],
    parameters:{
      type:'object',
      properties:{
        title:{type:'string',minLength:1,maxLength:120},
        chart_type:{type:'string',enum:['bar','line','pie']},
        labels:{type:'array',minItems:1,maxItems:8,items:{type:'string',maxLength:40}},
        values:{type:'array',minItems:1,maxItems:8,items:{type:'number',minimum:0,maximum:1000}}
      },
      required:['title','chart_type','labels','values'],
      additionalProperties:false
    },
    handler:args=>{
      if(args.labels.length!==args.values.length)throw Error('Mismatched chart data');
      return {blocks:[{type:'chart',chartType:args.chart_type,title:args.title,labels:args.labels,values:args.values}]};
    }
  });
  const chart=await runCapabilityLoop(model,[
    {role:'system',content:'You can discover tools with discover_capabilities. The user asks for a chart. Discover the relevant capability, call it with the user data, and then briefly report completion.'},
    {role:'user',content:'请把下面数据制作成柱状图：一月 2，二月 4，三月 7。标题为每月阅读量。'}
  ],registry,{maxRounds:5,maxCalls:4});
  if(!chart.blocks.some(block=>block.type==='chart'&&block.chartType==='bar'))throw Error('The model did not discover and execute the chart capability');
  report.chart_test={answer:chart.answer,events:chart.events,blocks:chart.blocks};
  report.checks.capability_discovery=true;
  report.checks.chart_tool_executed=true;
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
