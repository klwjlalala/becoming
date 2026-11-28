import {mkdirSync,writeFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {Gateway} from '../agent.mjs';

const output=resolve(process.env.TOOL_CALL_REPORT||'agent-runtime/artifacts/tool-call-probe.json');
const report={test:'native-function-tool-call-probe',model_calls:1,provider_response:null};
const model=new Gateway(process.env.BECOMING_GATEWAY||'http://127.0.0.1:8000');
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
  report.status='supported';
  report.checks={native_tool_call:true,forced_tool_choice:true,arguments_valid:true};
}catch(error){
  report.status='unsupported_or_incompatible';
  report.error=error.message;
  process.exitCode=1;
}finally{
  mkdirSync(dirname(output),{recursive:true});
  writeFileSync(output,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}
