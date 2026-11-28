import test from 'node:test';
import assert from 'node:assert/strict';
import {CapabilityRegistry,runCapabilityLoop} from '../capabilities/registry.mjs';

function chartRegistry(){
  const registry=new CapabilityRegistry();
  registry.register({
    name:'chart_create',
    description:'Create a structured chart from user data. Supports bar, line and pie charts.',
    category:'visualization',
    keywords:['图表','可视化','chart','diagram'],
    parameters:{
      type:'object',
      properties:{
        title:{type:'string',minLength:1,maxLength:120},
        chart_type:{type:'string',enum:['bar','line','pie']},
        labels:{type:'array',minItems:1,maxItems:20,items:{type:'string',maxLength:80}},
        values:{type:'array',minItems:1,maxItems:20,items:{type:'number',minimum:0,maximum:1000000}}
      },
      required:['title','chart_type','labels','values'],
      additionalProperties:false
    },
    handler:args=>({summary:'Chart created',blocks:[{type:'chart',chartType:args.chart_type,title:args.title,labels:args.labels,values:args.values}]})
  });
  return registry;
}

test('capability discovery activates a tool and executes native function calls',async()=>{
  const registry=chartRegistry(),seen=[];
  const model={completeStructured:async(messages,{tools})=>{
    seen.push({messages,tools});
    if(seen.length===1)return {text:'',tool_calls:[{id:'call-discover',type:'function',function:{name:'discover_capabilities',arguments:'{"query":"请创建图表"}'}}]};
    if(seen.length===2){
      assert.ok(tools.some(tool=>tool.function.name==='chart_create'),'Discovered capability was not activated');
      return {text:'',tool_calls:[{id:'call-chart',type:'function',function:{name:'chart_create',arguments:JSON.stringify({title:'每月阅读量',chart_type:'bar',labels:['一月','二月','三月'],values:[2,4,7]})}}]};
    }
    assert.ok(messages.some(message=>message.role==='tool'&&message.tool_call_id==='call-chart'));
    return {text:'已经根据数据生成柱状图。',tool_calls:[]};
  }};
  const result=await runCapabilityLoop(model,[{role:'system',content:'帮助用户完成任务。'},{role:'user',content:'把阅读量画成图表。'}],registry);
  assert.equal(result.answer,'已经根据数据生成柱状图。');
  assert.equal(result.tool_calls,2);
  assert.equal(result.rounds,3);
  assert.deepEqual(result.events.map(event=>event.name),['discover_capabilities','chart_create']);
  assert.equal(result.blocks.length,1);
  assert.equal(result.blocks[0].type,'chart');
  assert.equal(result.blocks[0].values[2],7);
});

test('capability schema rejects missing, extra and invalid values before execution',async()=>{
  const registry=chartRegistry();let calls=0;
  const item=registry.tools.get('chart_create');item.handler=()=>{calls++;return {ok:true};};
  const missing=await registry.execute('chart_create',{title:'阅读量',chart_type:'bar',labels:['一月']});
  const extra=await registry.execute('chart_create',{title:'阅读量',chart_type:'bar',labels:['一月'],values:[1],admin:true});
  const invalid=await registry.execute('chart_create',{title:'阅读量',chart_type:'scatter',labels:['一月'],values:[1]});
  assert.equal(missing.ok,false);assert.equal(extra.ok,false);assert.equal(invalid.ok,false);
  assert.equal(calls,0);
});

test('unknown tools and malformed JSON are rejected without executing handlers',async()=>{
  const registry=chartRegistry();
  assert.deepEqual(await registry.execute('not_registered',{}),{ok:false,error:'capability_unavailable'});
  const invalid=await registry.execute('chart_create','{invalid');
  assert.equal(invalid.ok,false);
});

test('capability loop enforces call and round limits',async()=>{
  const registry=chartRegistry();
  const model={completeStructured:async()=>({text:'',tool_calls:[{id:'x',type:'function',function:{name:'discover_capabilities',arguments:'{"query":"图表"}'}}]})};
  await assert.rejects(runCapabilityLoop(model,[{role:'user',content:'画图'}],registry,{maxCalls:1,maxRounds:2}),/round limit|call limit/);
});

test('registry exposes only enabled capabilities to discovery',()=>{
  const registry=chartRegistry();
  registry.register({name:'disabled_tool',description:'Disabled capability',category:'other',keywords:['disabled'],enabled:false,parameters:{type:'object',properties:{},additionalProperties:false},handler:()=>({})});
  const result=registry.discover('disabled');
  assert.deepEqual(result.activate,[]);
  assert.ok(registry.initialNames().includes('discover_capabilities'));
});
