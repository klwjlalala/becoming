const NAME=/^[A-Za-z0-9_-]{1,64}$/;
const isObject=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const jsonSize=value=>Buffer.byteLength(JSON.stringify(value));

function validateValue(schema,value,path='args'){
  if(!isObject(schema))throw Error('Invalid capability schema');
  const type=schema.type;
  const fail=()=>{throw Error('Invalid arguments at '+path);};
  if(type==='object'){
    if(!isObject(value))fail();
    const properties=schema.properties??{};
    if(!isObject(properties))throw Error('Invalid capability object schema');
    const required=schema.required??[];
    if(!Array.isArray(required)||required.some(k=>typeof k!=='string'))throw Error('Invalid capability required list');
    for(const key of required)if(!Object.hasOwn(value,key))fail();
    if(schema.additionalProperties!==true&&Object.keys(value).some(key=>!Object.hasOwn(properties,key)))fail();
    for(const [key,item] of Object.entries(value))if(Object.hasOwn(properties,key))validateValue(properties[key],item,path+'.'+key);
    return value;
  }
  if(type==='array'){
    if(!Array.isArray(value)||(schema.minItems!==undefined&&value.length<schema.minItems)||(schema.maxItems!==undefined&&value.length>schema.maxItems))fail();
    if(schema.items)for(let i=0;i<value.length;i++)validateValue(schema.items,value[i],path+'['+i+']');
    return value;
  }
  if(type==='string'){
    if(typeof value!=='string'||(schema.minLength!==undefined&&value.length<schema.minLength)||(schema.maxLength!==undefined&&value.length>schema.maxLength))fail();
    if(schema.enum&&!schema.enum.includes(value))fail();
    return value;
  }
  if(type==='integer'){
    if(!Number.isSafeInteger(value))fail();
    if(schema.minimum!==undefined&&value<schema.minimum)fail();
    if(schema.maximum!==undefined&&value>schema.maximum)fail();
    return value;
  }
  if(type==='number'){
    if(typeof value!=='number'||!Number.isFinite(value))fail();
    if(schema.minimum!==undefined&&value<schema.minimum)fail();
    if(schema.maximum!==undefined&&value>schema.maximum)fail();
    return value;
  }
  if(type==='boolean'){if(typeof value!=='boolean')fail();return value;}
  if(type==='null'){if(value!==null)fail();return value;}
  throw Error('Unsupported capability schema type: '+String(type));
}

function queryTerms(query){
  const terms=new Set((query.toLowerCase().match(/[a-z0-9_-]+/g)||[]));
  for(const run of query.match(/[\u3400-\u9fff]+/g)||[]){
    if(run.length<=2)terms.add(run);
    else for(let i=0;i<run.length-1;i++)terms.add(run.slice(i,i+2));
  }
  return [...terms].filter(term=>term.length>1);
}

export class CapabilityRegistry{
  constructor({maxDiscovery=8}={}){
    this.tools=new Map();
    this.maxDiscovery=maxDiscovery;
    this.register({
      name:'discover_capabilities',
      description:'Discover additional tools that can help with the current task. Call this when a required capability is not in the currently available tool list.',
      category:'system',
      keywords:['discover','search tools','find tools','能力','工具','发现'],
      alwaysAvailable:true,
      parameters:{type:'object',properties:{query:{type:'string',minLength:2,maxLength:160}},required:['query'],additionalProperties:false},
      handler:({query})=>this.discover(query)
    });
  }
  register({name,description,parameters,handler,category='general',keywords=[],alwaysAvailable=false,enabled=true,replace=false}){
    if(typeof name!=='string'||!NAME.test(name)||name==='discover_capabilities'&&this.tools.has(name))throw Error('Invalid or reserved capability name');
    if(typeof description!=='string'||!description.trim()||description.length>2048)throw Error('Invalid capability description');
    if(!isObject(parameters)||parameters.type!=='object'||typeof handler!=='function')throw Error('Invalid capability registration');
    if(!Array.isArray(keywords)||keywords.some(k=>typeof k!=='string'||k.length>80))throw Error('Invalid capability keywords');
    if(this.tools.has(name)&&!replace)throw Error('Capability already registered: '+name);
    this.tools.set(name,{name,description:description.trim(),parameters:structuredClone(parameters),handler,category,keywords:[...keywords],alwaysAvailable:!!alwaysAvailable,enabled:!!enabled});
    return this;
  }
  has(name){return this.tools.has(name)&&this.tools.get(name).enabled;}
  list({enabledOnly=true}={}){
    return [...this.tools.values()].filter(item=>!enabledOnly||item.enabled).map(({name,description,parameters,category,keywords,alwaysAvailable})=>({name,description,parameters:structuredClone(parameters),category,keywords:[...keywords],alwaysAvailable}));
  }
  initialNames(){return [...this.tools.values()].filter(item=>item.enabled&&item.alwaysAvailable).map(item=>item.name);}
  toolSpecs(names){
    return names.map(name=>this.tools.get(name)).filter(item=>item?.enabled).map(item=>({type:'function',function:{name:item.name,description:item.description,parameters:structuredClone(item.parameters)}}));
  }
  discover(query){
    if(typeof query!=='string'||query.trim().length<2||query.length>160)throw Error('Invalid discovery query');
    const terms=queryTerms(query),matches=[];
    for(const item of this.tools.values()){
      if(!item.enabled||item.name==='discover_capabilities')continue;
      const haystack=[item.name,item.description,item.category,...item.keywords].join(' ').toLowerCase();
      let score=haystack.includes(query.toLowerCase())?10:0;
      for(const term of terms)if(haystack.includes(term))score+=1;
      if(score>0)matches.push({item,score});
    }
    matches.sort((a,b)=>b.score-a.score||a.item.name.localeCompare(b.item.name));
    const selected=matches.slice(0,this.maxDiscovery).map(x=>x.item);
    return {activate:selected.map(item=>item.name),capabilities:selected.map(({name,description,category,keywords})=>({name,description,category,keywords}))};
  }
  async execute(name,args,context={}){
    const item=this.tools.get(name);
    if(!item||!item.enabled)return {ok:false,error:'capability_unavailable'};
    try{
      if(typeof args==='string')args=JSON.parse(args);
      validateValue(item.parameters,args);
      const result=await item.handler(args,{...context,capability:name,registry:this});
      const envelope={ok:true,result};
      if(jsonSize(envelope)>48000)throw Error('Capability result too large');
      return envelope;
    }catch(error){
      return {ok:false,error:error?.message?.slice(0,300)||'capability_execution_failed'};
    }
  }
}

export async function runCapabilityLoop(model,messages,registry,{signal,onToken,conversationId='default',maxRounds=6,maxCalls=8}={}){
  if(!model||typeof model.completeStructured!=='function'&&typeof model.streamStructured!=='function')throw Error('Model does not support structured tool calling');
  const context=messages.map(message=>({...message}));
  const active=new Set(registry.initialNames());
  const events=[],blocks=[];
  let totalCalls=0,accumulatedText='';
  for(let round=0;round<maxRounds;round++){
    const specs=registry.toolSpecs([...active]);
    let roundText='';
    const roundToken=chunk=>{
      if(!roundText&&accumulatedText)onToken?.('\\n\\n');
      roundText+=chunk;onToken?.(chunk);
    };
    const response=typeof model.streamStructured==='function'
      ?await model.streamStructured(context,{tools:specs,tool_choice:'auto',signal,onToken:roundToken})
      :await model.completeStructured(context,{tools:specs,tool_choice:'auto',signal});
    if(response.text){
      if(!response.streamed){if(accumulatedText)onToken?.('\\n\\n');onToken?.(response.text);}
      accumulatedText+=response.text;
    }
    const calls=response.tool_calls??[];
    if(!calls.length){
      const answer=accumulatedText.trim();
      if(!answer)throw Error('Model returned neither text nor tool calls');
      return {answer,events,blocks,tool_calls:totalCalls,rounds:round+1};
    }
    context.push({role:'assistant',content:response.text||null,tool_calls:calls});
    for(const call of calls){
      totalCalls++;
      if(totalCalls>maxCalls)throw Error('Capability tool-call limit reached');
      const name=call.function.name;
      let execution;
      try{execution=await registry.execute(name,call.function.arguments,{signal,conversationId,round,callId:call.id});}
      catch(error){execution={ok:false,error:'capability_execution_failed'};}
      const result=execution.result;
      if(Array.isArray(result?.activate))for(const item of result.activate)if(registry.has(item))active.add(item);
      if(Array.isArray(result?.blocks))blocks.push(...result.blocks);
      events.push({name,status:execution.ok?'completed':'failed',result:execution.ok?result:null,error:execution.ok?null:execution.error,call_id:call.id});
      context.push({role:'tool',tool_call_id:call.id,content:JSON.stringify(execution)});
    }
  }
  throw Error('Capability tool-call round limit reached');
}
