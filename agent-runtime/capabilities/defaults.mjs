export function registerDefaultCapabilities({registry,growth,gateway,assetStore,enableImage=true}){
  if(!registry)throw Error('Capability registry is required');
  if(growth)growth.registerCapabilities(registry);
  registry.register({
    name:'chart_create',
    description:'Create a visual chart from structured data. Use for comparing values or showing trends; supports bar, line and pie charts.',
    category:'visualization',
    keywords:['图表','数据可视化','趋势','比较','chart','visualization'],
    parameters:{
      type:'object',
      properties:{
        title:{type:'string',minLength:1,maxLength:120},
        chart_type:{type:'string',enum:['bar','line','pie']},
        labels:{type:'array',minItems:1,maxItems:16,items:{type:'string',minLength:1,maxLength:80}},
        values:{type:'array',minItems:1,maxItems:16,items:{type:'number',minimum:0,maximum:1000000}}
      },
      required:['title','chart_type','labels','values'],
      additionalProperties:false
    },
    handler:args=>{
      if(args.labels.length!==args.values.length)throw Error('Chart labels and values must have the same length');
      return {blocks:[{type:'chart',chartType:args.chart_type,title:args.title,labels:args.labels,values:args.values}]};
    }
  });
  registry.register({
    name:'diagram_create',
    description:'Create a structured relationship or process diagram from labeled nodes and directed connections.',
    category:'visualization',
    keywords:['关系图','流程图','思维导图','结构图','diagram','flowchart','mind map'],
    parameters:{
      type:'object',
      properties:{
        title:{type:'string',minLength:1,maxLength:120},
        layout:{type:'string',enum:['vertical','horizontal']},
        nodes:{type:'array',minItems:2,maxItems:10,items:{type:'object',properties:{id:{type:'string',minLength:1,maxLength:24},label:{type:'string',minLength:1,maxLength:48},description:{type:'string',maxLength:80}},required:['id','label'],additionalProperties:false}},
        edges:{type:'array',maxItems:16,items:{type:'object',properties:{from:{type:'string',minLength:1,maxLength:24},to:{type:'string',minLength:1,maxLength:24},label:{type:'string',maxLength:40}},required:['from','to'],additionalProperties:false}}
      },
      required:['title','layout','nodes','edges'],
      additionalProperties:false
    },
    handler:args=>{
      const ids=new Set(args.nodes.map(node=>node.id));
      if(ids.size!==args.nodes.length||args.edges.some(edge=>!ids.has(edge.from)||!ids.has(edge.to)||edge.from===edge.to))throw Error('Diagram contains duplicate or unknown node references');
      return {blocks:[{type:'diagram',title:args.title,layout:args.layout,nodes:args.nodes,edges:args.edges}]};
    }
  });
  if(enableImage){
    if(!gateway||!assetStore)throw Error('Image generation requires a gateway and local asset store');
    registry.register({
      name:'image_generate',
      description:'Generate an original image to illustrate a scene, idea or concept. Use when a visual would materially help the user; describe the intended image precisely.',
      category:'visualization',
      keywords:['图片生成','画图','插画','场景图','image generation','illustration','visual'],
      parameters:{
        type:'object',
        properties:{
          prompt:{type:'string',minLength:8,maxLength:4000},
          size:{type:'string',enum:['1024x1024','1024x1536','1536x1024']},
          alt:{type:'string',maxLength:300},
          caption:{type:'string',maxLength:500}
        },
        required:['prompt'],
        additionalProperties:false
      },
      handler:async args=>{
        const generated=await gateway.generateImage({prompt:args.prompt,size:args.size||'1024x1024'});
        const asset=assetStore.save(generated.buffer,generated.mime_type);
        return {asset_id:asset.id,mime_type:asset.mime_type,blocks:[{type:'image',asset_id:asset.id,alt:args.alt||'AI 生成的辅助图片',caption:args.caption||generated.revised_prompt||''}]};
      }
    });
  }
  return registry;
}
