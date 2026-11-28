import test from 'node:test';
import assert from 'node:assert/strict';
import {CapabilityRegistry,runCapabilityLoop} from '../capabilities/registry.mjs';
import {Agent} from '../agent.mjs';
import {Store} from '../store.mjs';
import {GrowthStore,GrowthTools} from '../growth.mjs';

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

test('capability loop preserves streamed preambles and final answers across tool rounds',async()=>{
  const registry=new CapabilityRegistry();let round=0;const tokens=[];
  registry.register({name:'quick_tool',description:'A simple test capability.',category:'test',keywords:['quick'],parameters:{type:'object',properties:{},additionalProperties:false},handler:()=>({ok:true})});
  const model={streamStructured:async(messages,{onToken})=>{
    round++;
    if(round===1){onToken('我来执行工具。');return {text:'我来执行工具。',streamed:true,tool_calls:[{id:'quick-1',type:'function',function:{name:'quick_tool',arguments:'{}'}}]};}
    onToken('已经完成。');return {text:'已经完成。',streamed:true,tool_calls:[]};
  }};
  const result=await runCapabilityLoop(model,[{role:'user',content:'执行一下'}],registry,{onToken:token=>tokens.push(token)});
  assert.equal(result.answer,'我来执行工具。\\n\\n已经完成。');
  assert.equal(tokens.join(''),'我来执行工具。\\n\\n已经完成。');
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

test('Agent integrates native capability calls and returns generated content blocks',async()=>{
  const registry=new CapabilityRegistry();
  registry.register({
    name:'make_visual',
    description:'Create a simple visual artifact for the user.',
    category:'visualization',
    keywords:['visual','图像','图表'],
    alwaysAvailable:true,
    parameters:{type:'object',properties:{label:{type:'string',minLength:1,maxLength:40}},required:['label'],additionalProperties:false},
    handler:({label})=>({blocks:[{type:'image',asset_id:'asset-test',alt:label}]})
  });
  let call=0;
  const model={completeStructured:async()=>{
    call++;
    if(call===1)return {text:'',tool_calls:[{id:'visual-1',type:'function',function:{name:'make_visual',arguments:'{"label":"测试图"}'}}]};
    return {text:'已经生成测试图。',tool_calls:[]};
  }};
  const store=new Store(':memory:'),agent=new Agent(store,model,{capabilities:registry});
  const turn=await agent.reply('请生成一个简单的视觉示例。');
  assert.equal(turn.assistant,'已经生成测试图。');
  assert.equal(turn.content_blocks.length,1);
  assert.equal(turn.content_blocks[0].asset_id,'asset-test');
  assert.equal(store.history(1)[0].content_blocks[0].asset_id,'asset-test','Generated content blocks must survive history reload');
  assert.equal(store.turn(turn.id).content_blocks[0].type,'image');
  assert.equal(turn.event.capabilities[0].name,'make_visual');
  assert.equal(turn.event.capabilities[0].status,'completed');
  store.close();
});
test('native growth tools preserve the existing user-confirmation boundary',async()=>{
  const store=new Store(':memory:'),growthStore=new GrowthStore(':memory:');
  const growth=new GrowthTools({complete:async()=>''},growthStore);
  const registry=new CapabilityRegistry();growth.registerCapabilities(registry);
  let call=0;
  const model={completeStructured:async()=>{
    call++;
    if(call===1)return {text:'',tool_calls:[{id:'discover-growth',type:'function',function:{name:'discover_capabilities',arguments:'{"query":"成长目标"}'}}]};
    if(call===2)return {text:'',tool_calls:[{id:'create-growth',type:'function',function:{name:'create_goal',arguments:'{"text":"阅读"}'}}]};
    return {text:'我已经准备好新增“阅读”目标，但还没有保存。请确认后再写入。',tool_calls:[]};
  }};
  const agent=new Agent(store,model,{growth,capabilities:registry});
  const turn=await agent.reply('帮我创建一个成长目标：阅读。');
  assert.equal(turn.pending_growth.preview.tool,'create_goal');
  assert.equal(growthStore.read('list_goals',{}).items.length,0,'A proposed mutation must not be persisted before confirmation');
  assert.deepEqual(turn.event.capabilities.map(event=>event.name),['discover_capabilities','create_goal']);
  const committed=await agent.reply('/confirm '+turn.pending_growth.token);
  assert.equal(committed.event.growth.status,'committed');
  assert.equal(growthStore.read('list_goals',{}).items.length,1);
  growthStore.close();store.close();
});
test('diagram capability validates node references and returns a renderable block',async()=>{
  const registry=new CapabilityRegistry();
  registry.register({
    name:'diagram_create',
    description:'Create a relationship diagram or process flow from labeled nodes and edges.',
    category:'visualization',
    keywords:['关系图','流程图','diagram'],
    parameters:{
      type:'object',
      properties:{
        title:{type:'string',minLength:1,maxLength:80},
        layout:{type:'string',enum:['vertical','horizontal']},
        nodes:{type:'array',minItems:2,maxItems:5,items:{type:'object',properties:{id:{type:'string',minLength:1,maxLength:24},label:{type:'string',minLength:1,maxLength:48},description:{type:'string',maxLength:80}},required:['id','label'],additionalProperties:false}},
        edges:{type:'array',maxItems:8,items:{type:'object',properties:{from:{type:'string'},to:{type:'string'},label:{type:'string'}},required:['from','to'],additionalProperties:false}}
      },
      required:['title','layout','nodes','edges'],
      additionalProperties:false
    },
    handler:args=>{
      const ids=new Set(args.nodes.map(node=>node.id));
      if(ids.size!==args.nodes.length||args.edges.some(edge=>!ids.has(edge.from)||!ids.has(edge.to)||edge.from===edge.to))throw Error('Invalid edge reference');
      return {blocks:[{type:'diagram',title:args.title,layout:args.layout,nodes:args.nodes,edges:args.edges}]};
    }
  });
  const result=await registry.execute('diagram_create',{title:'目标关系',layout:'vertical',nodes:[{id:'a',label:'兴趣'},{id:'b',label:'行动'}],edges:[{from:'a',to:'b',label:'推动'}]});
  assert.equal(result.ok,true);
  assert.equal(result.result.blocks[0].type,'diagram');
  const invalid=await registry.execute('diagram_create',{title:'错误关系',layout:'vertical',nodes:[{id:'a',label:'A'},{id:'b',label:'B'}],edges:[{from:'a',to:'missing'}]});
  assert.equal(invalid.ok,false);
});
test('registry exposes only enabled capabilities to discovery',()=>{
  const registry=chartRegistry();
  registry.register({name:'disabled_tool',description:'Disabled capability',category:'other',keywords:['disabled'],enabled:false,parameters:{type:'object',properties:{},additionalProperties:false},handler:()=>({})});
  const result=registry.discover('disabled');
  assert.deepEqual(result.activate,[]);
  assert.ok(registry.initialNames().includes('discover_capabilities'));
});
