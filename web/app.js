const $ = id => document.getElementById(id);
const welcomeNode = $('welcome');
const state = {turns:[],before:null,hasMore:false,pendingGrowth:null,busy:false,controller:null,demo:false};

function toast(message){
  const node=$('toast');node.textContent=message;node.classList.add('visible');
  clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.classList.remove('visible'),2600);
}
async function api(path,options={}){
  const response=await fetch(path,options),data=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(data.error||'请求失败，请稍后重试');
  return data;
}
function formatTime(value){
  if(!value)return '';
  return new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit'}).format(new Date(value));
}
function dateLabel(value){
  const date=new Date(value),now=new Date(),key=d=>[d.getFullYear(),d.getMonth(),d.getDate()].join('-');
  const yesterday=new Date(now.getFullYear(),now.getMonth(),now.getDate()-1);
  if(key(date)===key(now))return '今天';
  if(key(date)===key(yesterday))return '昨天';
  return new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'long',day:'numeric'}).format(date);
}
function makeButton(label,className,handler){
  const button=document.createElement('button');button.type='button';button.className=className;button.textContent=label;
  button.addEventListener('click',handler);return button;
}
function appendInline(parent,text){
  const pattern=/(!\[[^\]]*\]\([^)]+\)|\*\*[^*]+\*\*|~~[^~]+~~|`[^`]+`|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  let last=0,match;
  while((match=pattern.exec(text))){
    if(match.index>last)parent.append(document.createTextNode(text.slice(last,match.index)));
    const value=match[0];
    if(value.startsWith('![')){parent.append(document.createTextNode(value));}
    else if(value.startsWith('**')){const el=document.createElement('strong');el.textContent=value.slice(2,-2);parent.append(el);}
    else if(value.startsWith('~~')){const el=document.createElement('del');el.textContent=value.slice(2,-2);parent.append(el);}
    else if(value.startsWith('`')){const el=document.createElement('code');el.textContent=value.slice(1,-1);parent.append(el);}
    else if(value.startsWith('*')){const el=document.createElement('em');el.textContent=value.slice(1,-1);parent.append(el);}
    else{
      const link=value.match(/^\[([^\]]+)\]\(([^)]+)\)$/),anchor=document.createElement('a');
      let href=null;try{const parsed=new URL(link[2],location.origin);if(parsed.protocol==='http:'||parsed.protocol==='https:')href=parsed.href;}catch{}
      if(href){anchor.href=href;anchor.target='_blank';anchor.rel='noopener noreferrer';anchor.textContent=link[1];parent.append(anchor);}
      else parent.append(document.createTextNode(value));
    }
    last=pattern.lastIndex;
  }
  if(last<text.length)parent.append(document.createTextNode(text.slice(last)));
}
function markdownTableCells(line){return line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(cell=>cell.trim());}
function isMarkdownTableDivider(line){return /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);}
function renderMarkdown(text){
  const root=document.createElement('div');root.className='markdown-content';
  const lines=String(text||'').replace(/\r\n/g,'\n').split('\n');
  let i=0;
  while(i<lines.length){
    const line=lines[i];
    if(!line.trim()){i++;continue;}
    if(/^\s*```/.test(line)){
      const language=line.trim().slice(3).trim(),parts=[];i++;
      while(i<lines.length&&!/^\s*```/.test(lines[i]))parts.push(lines[i++]);
      if(i<lines.length)i++;
      const pre=document.createElement('pre'),code=document.createElement('code');if(language)code.dataset.language=language;code.textContent=parts.join('\n');pre.append(code);root.append(pre);continue;
    }
    const heading=line.match(/^\s*(#{1,6})\s+(.+)$/);
    if(heading){const el=document.createElement('h'+heading[1].length);appendInline(el,heading[2]);root.append(el);i++;continue;}
    if(/^\s*(?:---+|\*\*\*|___)\s*$/.test(line)){root.append(document.createElement('hr'));i++;continue;}
    if(i+1<lines.length&&line.includes('|')&&isMarkdownTableDivider(lines[i+1])){
      const table=document.createElement('table'),thead=document.createElement('thead'),tbody=document.createElement('tbody'),header=markdownTableCells(line),headRow=document.createElement('tr');
      for(const value of header){const cell=document.createElement('th');appendInline(cell,value);headRow.append(cell);}
      thead.append(headRow);i+=2;
      while(i<lines.length&&lines[i].trim().startsWith('|')){
        const values=markdownTableCells(lines[i]),row=document.createElement('tr');
        for(let col=0;col<header.length;col++){const cell=document.createElement('td');appendInline(cell,values[col]||'');row.append(cell);}
        tbody.append(row);i++;
      }
      table.append(thead,tbody);root.append(table);continue;
    }
    if(/^\s*(?:[-*+]\s+|\d+\.\s+)/.test(line)){
      const ordered=/^\s*\d+\.\s+/.test(line),list=document.createElement(ordered?'ol':'ul');
      while(i<lines.length&&/^\s*(?:[-*+]\s+|\d+\.\s+)/.test(lines[i])){
        const item=lines[i++].replace(/^\s*(?:[-*+]\s+|\d+\.\s+)/,'');
        const li=document.createElement('li');appendInline(li,item);list.append(li);
      }
      root.append(list);continue;
    }
    if(/^\s*>/.test(line)){
      const quote=document.createElement('blockquote'),parts=[];
      while(i<lines.length&&/^\s*>/.test(lines[i]))parts.push(lines[i++].replace(/^\s*>\s?/,''));
      const paragraph=document.createElement('p');appendInline(paragraph,parts.join(' '));quote.append(paragraph);root.append(quote);continue;
    }
    const parts=[line.trim()];i++;
    while(i<lines.length&&lines[i].trim()&&!/^\s*(?:#{1,6}\s|```|>|[-*+]\s+|\d+\.\s+)/.test(lines[i])&&!/^\s*(?:---+|\*\*\*|___)\s*$/.test(lines[i])){
      if(i+1<lines.length&&lines[i].includes('|')&&isMarkdownTableDivider(lines[i+1]))break;
      parts.push(lines[i].trim());i++;
    }
    const paragraph=document.createElement('p');appendInline(paragraph,parts.join(' '));root.append(paragraph);
  }
  return root;
}
function svgNode(name,attributes={}){
  const node=document.createElementNS('http://www.w3.org/2000/svg',name);
  for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));
  return node;
}
function renderChartBlock(block){
  const labels=Array.isArray(block.labels)?block.labels:[],values=Array.isArray(block.values)?block.values:[];
  if(!labels.length||labels.length!==values.length||values.some(value=>typeof value!=='number'||!Number.isFinite(value)||value<0))return null;
  const figure=document.createElement('figure');figure.className='agent-chart-card';
  if(block.title){const title=document.createElement('figcaption');title.className='agent-chart-title';title.textContent=block.title;figure.append(title);}
  const svg=svgNode('svg',{viewBox:'0 0 680 340',role:'img','aria-label':block.title||'数据图表',class:'agent-chart-svg'});
  const type=block.chartType||'bar',max=Math.max(...values,1),left=54,right=22,top=24,bottom=70,width=680-left-right,height=340-top-bottom;
  if(type==='pie'){
    const total=values.reduce((a,b)=>a+b,0)||1,cx=245,cy=165,r=118;let angle=-Math.PI/2;
    values.forEach((value,index)=>{
      const next=angle+Math.PI*2*value/total,x1=cx+r*Math.cos(angle),y1=cy+r*Math.sin(angle),x2=cx+r*Math.cos(next),y2=cy+r*Math.sin(next),large=next-angle>Math.PI?1:0;
      const path=svgNode('path',{d:`M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`,class:'agent-chart-slice',style:`--slice-index:${index}`});
      svg.append(path);angle=next;
    });
    const legend=svgNode('g',{class:'agent-chart-legend'});
    labels.forEach((label,index)=>{
      const y=70+index*34,swatch=svgNode('rect',{x:430,y:y-12,width:13,height:13,rx:3,class:'agent-chart-swatch',style:`--slice-index:${index}`}),text=svgNode('text',{x:452,y,class:'agent-chart-label'});
      text.textContent=label+' · '+values[index];legend.append(swatch,text);
    });svg.append(legend);
  }else{
    for(let tick=0;tick<=4;tick++){
      const y=top+height*(tick/4),line=svgNode('line',{x1:left,y1:y,x2:left+width,y2:y,class:'agent-chart-gridline'}),label=svgNode('text',{x:left-10,y:y+4,'text-anchor':'end',class:'agent-chart-axis-label'});
      label.textContent=String(Math.round(max*(1-tick/4)));svg.append(line,label);
    }
    const points=values.map((value,index)=>({x:left+width*((index+.5)/values.length),y:top+height*(1-value/max),value}));
    if(type==='line'){
      const path=svgNode('polyline',{points:points.map(p=>p.x+','+p.y).join(' '),class:'agent-chart-line'});svg.append(path);
      points.forEach(point=>svg.append(svgNode('circle',{cx:point.x,cy:point.y,r:5,class:'agent-chart-point'})));
    }else{
      const slot=width/values.length,barWidth=Math.min(64,slot*.58);
      points.forEach(point=>svg.append(svgNode('rect',{x:point.x-barWidth/2,y:point.y,width:barWidth,height:top+height-point.y,rx:5,class:'agent-chart-bar'})));
    }
    points.forEach((point,index)=>{
      const valueLabel=svgNode('text',{x:point.x,y:point.y-9,'text-anchor':'middle',class:'agent-chart-value'});valueLabel.textContent=String(point.value);
      const label=svgNode('text',{x:point.x,y:top+height+25,'text-anchor':'middle',class:'agent-chart-axis-label'});label.textContent=labels[index].length>10?labels[index].slice(0,9)+'…':labels[index];
      svg.append(valueLabel,label);
    });
  }
  figure.append(svg);return figure;
}
function renderContentBlocks(container,blocks=[]){
  for(const block of blocks){
    if(!block||typeof block!=='object')continue;
    if(block.type==='chart'){
      const chart=renderChartBlock(block);if(chart)container.append(chart);
    }else if(block.type==='image'){
      const src=typeof block.asset_id==='string'?'/api/assets/'+encodeURIComponent(block.asset_id):(typeof block.src==='string'&&block.src.startsWith('/api/assets/')?block.src:null);
      if(!src)continue;
      const figure=document.createElement('figure');figure.className='agent-image-card';
      const img=document.createElement('img');img.src=src;img.alt=String(block.alt||'生成的图片').slice(0,300);img.loading='lazy';figure.append(img);
      if(block.caption){const caption=document.createElement('figcaption');caption.textContent=block.caption;figure.append(caption);}
      container.append(figure);
    }else if(block.type==='document'&&typeof block.asset_id==='string'){
      const link=document.createElement('a');link.className='agent-document-link';link.href='/api/assets/'+encodeURIComponent(block.asset_id);link.textContent=String(block.title||'打开文件');link.download='';container.append(link);
    }else if(block.type==='link'&&typeof block.url==='string'){
      let url=null;try{const parsed=new URL(block.url,location.origin);if(parsed.protocol==='http:'||parsed.protocol==='https:')url=parsed.href;}catch{}
      if(url){const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=String(block.title||url);container.append(link);}
    }
  }
}
function createMessage(role,text,turnId=null,createdAt=null,contentBlocks=[]){
  const row=document.createElement('article');row.className='message-row '+role;
  if(turnId)row.dataset.turnId=turnId;
  const avatar=document.createElement('div');avatar.className='message-avatar '+(role==='assistant'?'assistant-avatar':'user-avatar');
  avatar.textContent=role==='assistant'?'✦':'你';
  const body=document.createElement('div');body.className='message-body';
  const meta=document.createElement('div');meta.className='message-meta';
  const name=document.createElement('span');name.className='message-name';name.textContent=role==='assistant'?'AI 好友':'你';
  const time=document.createElement('time');time.className='message-time';time.textContent=formatTime(createdAt);
  meta.append(name,time);
  const bubble=document.createElement('div');bubble.className='message-bubble';bubble.dataset.copyText=text||'';
  if(role==='assistant'){bubble.append(renderMarkdown(text||''));renderContentBlocks(bubble,contentBlocks);}else bubble.textContent=text||'';
  body.append(meta,bubble);
  const actions=document.createElement('div');actions.className='message-actions';
  if(role==='assistant'){
    actions.append(makeButton('复制','message-action',async()=>{
      try{await navigator.clipboard.writeText(bubble.dataset.copyText||bubble.textContent);toast('已复制回复');}
      catch{toast('当前环境无法访问剪贴板');}
    }));
  }
  body.append(actions);
  if(role==='assistant')row.append(avatar,body);else row.append(body,avatar);
  return {row,bubble,meta,actions};
}
function renderGrowthCard(pending){
  const preview=pending?.preview;if(!preview)return null;
  const card=document.createElement('section');card.className='inline-card confirmation-card';
  const icon=document.createElement('div');icon.className='inline-card-icon';icon.textContent='↗';
  const content=document.createElement('div');content.className='inline-card-content';
  const title=document.createElement('strong');title.textContent='有一项变更需要你确认';
  const description=document.createElement('p'),args=preview.args||{};
  description.textContent=args.text||args.title||('操作：'+String(preview.tool||'记录变更'));
  const foot=document.createElement('div');foot.className='inline-card-foot';foot.textContent='确认后才会实际保存';
  content.append(title,description,foot);
  const actions=document.createElement('div');actions.className='inline-card-actions';
  actions.append(makeButton('暂不处理','subtle-button',()=>sendMessage('/cancel')));
  actions.append(makeButton('确认保存','primary-small',()=>sendMessage('/confirm '+pending.token)));
  card.append(icon,content,actions);return card;
}
function appendDateIfNeeded(container,turn,previousDate){
  const label=dateLabel(turn.created_at);
  if(label!==previousDate){
    const divider=document.createElement('div');divider.className='date-divider';
    const text=document.createElement('span');text.textContent=label;divider.append(text);container.append(divider);
  }
  return label;
}
function renderTurn(turn,container,pending=null){
  const group=document.createElement('div');group.className='turn-group';group.dataset.turnId=turn.id;
  const user=createMessage('user',turn.user,turn.id,turn.created_at);
  let assistantText=turn.assistant||'';
  if(assistantText.startsWith('尚未保存。请核对以下变更：'))assistantText=pending?'我整理了一项变更，先请你确认。':'有一项变更等待确认，但当前确认状态不可用，请重新发起请求。';
  if(assistantText.startsWith('已保存变更：'))assistantText='已保存这项变更。';
  const assistant=createMessage('assistant',assistantText,turn.id,turn.created_at,turn.content_blocks||[]);
  group.append(user.row,assistant.row);
  if(pending){const card=renderGrowthCard(pending);if(card)group.append(card);}
  container.append(group);return group;
}
function renderHistory(turns,{pending=null,highlightId=null,keepScroll=false}={}){
  const history=$('history'),welcome=welcomeNode,oldHeight=history.scrollHeight,oldTop=history.scrollTop;
  history.replaceChildren();
  if(!turns.length){welcome.hidden=false;history.append(welcome);}
  else welcome.hidden=true;
  let lastDate='';
  turns.forEach((turn,index)=>{
    lastDate=appendDateIfNeeded(history,turn,lastDate);
    renderTurn(turn,history,index===turns.length-1?pending:null);
  });
  $('load-older').hidden=!state.hasMore||state.demo;
  if(highlightId){
    const target=history.querySelector('[data-turn-id="'+CSS.escape(highlightId)+'"]');
    if(target){target.classList.add('highlighted');target.scrollIntoView({block:'center',behavior:'smooth'});}
  }else if(keepScroll)history.scrollTop=oldTop+(history.scrollHeight-oldHeight);
  else history.scrollTop=history.scrollHeight;
}
async function loadHistory({scroll=true,around=null}={}){
  const page=await api(around?'/api/history?around='+encodeURIComponent(around):'/api/history');
  state.turns=page.turns||[];state.before=page.before??null;
  state.hasMore=around?!!page.has_more_before:!!page.has_more;
  state.pendingGrowth=page.pending_growth||null;
  renderHistory(state.turns,{pending:state.pendingGrowth,highlightId:around,keepScroll:!scroll});
  if(scroll)$('history').scrollTop=$('history').scrollHeight;
}
async function loadOlder(){
  if(!state.before||!state.hasMore||state.busy)return;
  const button=$('load-older');button.disabled=true;
  const previousHeight=$('history').scrollHeight,previousTop=$('history').scrollTop;
  try{
    const page=await api('/api/history?before='+encodeURIComponent(state.before));
    state.turns=[...page.turns,...state.turns];state.before=page.before??null;state.hasMore=!!page.has_more;
    renderHistory(state.turns,{pending:state.pendingGrowth,keepScroll:true});
    $('history').scrollTop=previousTop+($('history').scrollHeight-previousHeight);
  }catch(error){toast(error.message);}
  finally{button.disabled=false;}
}
function parseFrame(frame){
  let event='message',data='';
  for(const line of frame.split(/\r?\n/)){
    if(line.startsWith('event:'))event=line.slice(6).trim();
    else if(line.startsWith('data:'))data+=line.slice(5).trimStart();
  }
  if(!data)return null;
  try{return {event,data:JSON.parse(data)};}catch{return null;}
}
async function consumeStream(response,onEvent){
  if(!response.body)throw new Error('当前环境不支持流式响应');
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',done=false,result=null;
  try{
    while(!done){
      const part=await reader.read();if(part.done)break;
      buffer+=decoder.decode(part.value,{stream:true});
      let match;
      while((match=/\r?\n\r?\n/.exec(buffer))){
        const frame=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length);
        const parsed=parseFrame(frame);if(!parsed)continue;
        if(parsed.event==='error')throw new Error(parsed.data.message||'回复失败');
        if(parsed.event==='done'){result=parsed.data.turn;done=true;break;}
        onEvent(parsed.event,parsed.data);
      }
    }
    if(!result&&buffer.trim()){
      const parsed=parseFrame(buffer);
      if(parsed?.event==='error')throw new Error(parsed.data.message||'回复失败');
      if(parsed?.event==='done')result=parsed.data.turn;
    }
    if(!result)throw new Error('连接中断，回复尚未完成');
    return result;
  }finally{try{reader.releaseLock();}catch{}}
}
function createPendingGroup(text){
  welcomeNode.hidden=true;
  if(!welcomeNode.isConnected)$('history').append(welcomeNode);
  const group=document.createElement('div');group.className='turn-group pending-group';
  const user=createMessage('user',text,null,new Date().toISOString());
  const assistant=createMessage('assistant','正在认真组织回复…',null,new Date().toISOString());
  assistant.bubble.classList.add('streaming-placeholder');
  group.append(user.row,assistant.row);$('history').append(group);$('history').scrollTop=$('history').scrollHeight;
  return {group,assistant};
}
function addRetry(assistant,text,requestId,group,statusLabel){
  assistant.actions.replaceChildren();assistant.meta.querySelector('.message-time').textContent=statusLabel;
  assistant.actions.append(makeButton('重试','message-action retry-action',()=>runRequest(text,requestId,group,assistant)));
}
async function runRequest(text,requestId,group,assistant){
  if(state.busy)return;
  state.busy=true;state.controller=new AbortController();
  $('send-button').hidden=true;$('stop-button').hidden=false;$('message').disabled=true;
  group.querySelector('.stream-interruption')?.remove();
  assistant.bubble.textContent='';assistant.bubble.classList.add('streaming-placeholder');
  assistant.meta.querySelector('.message-time').textContent='正在回复';
  try{
    const response=await fetch('/api/chat/stream',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text,request_id:requestId}),signal:state.controller.signal
    });
    if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.error||'发送失败');}
    const turn=await consumeStream(response,(name,payload)=>{
      if(name==='token'){assistant.bubble.classList.remove('streaming-placeholder');assistant.bubble.textContent+=payload.text||'';$('history').scrollTop=$('history').scrollHeight;}
    });
    await loadHistory({scroll:true});
    if(turn.pending_growth)toast('有一项变更等待你确认');
  }catch(error){
    const saved=await api('/api/requests/'+encodeURIComponent(requestId)).catch(()=>({turn:null}));
    if(saved.turn)await loadHistory({scroll:true});
    else{
      assistant.bubble.classList.remove('streaming-placeholder');
      const stopped=error?.name==='AbortError';
      if(!assistant.bubble.textContent)assistant.bubble.textContent=stopped?'已停止回复，本轮内容未保存。':'这次没有成功获取回复。';
      else{
        const notice=document.createElement('div');notice.className='stream-interruption';
        notice.textContent=stopped?'回复已停止，以上内容未保存。':'回复中断，以上内容未保存。';
        assistant.bubble.after(notice);
      }
      addRetry(assistant,text,requestId,group,stopped?'已停止 · 未保存':'发送失败 · 未保存');
      toast(stopped?'已停止生成':error.message);
    }
  }finally{
    state.busy=false;state.controller=null;$('message').disabled=false;
    $('stop-button').hidden=true;$('send-button').hidden=false;updateSendState();$('message').focus();
  }
}
function sendMessage(raw){
  const text=(raw??$('message').value).trim();if(!text||state.busy)return;
  if(state.demo){state.demo=false;$('demo-notice').hidden=true;$('history').replaceChildren();}
  $('message').value='';resizeComposer();
  const requestId=crypto.randomUUID(),pending=createPendingGroup(text);
  return runRequest(text,requestId,pending.group,pending.assistant);
}
function updateSendState(){
  const hasText=$('message').value.trim().length>0;
  $('send-button').disabled=!hasText||state.busy;
  $('char-count').textContent=$('message').value.length+' / 16000';
}
function resizeComposer(){
  const input=$('message');input.style.height='auto';input.style.height=Math.min(input.scrollHeight,180)+'px';updateSendState();
}
function setTheme(theme){
  document.documentElement.dataset.theme=theme;localStorage.setItem('becoming-theme',theme);
  $('theme-toggle').querySelector('.nav-label').textContent=theme==='dark'?'切换浅色':'切换深色';
}
function showDemo(){
  state.demo=true;state.hasMore=false;$('load-older').hidden=true;$('welcome').hidden=true;$('demo-notice').hidden=false;
  const history=$('history');history.replaceChildren();
  const sample=[
    {user:'最近感觉有点拖延，明明有很多想做的事，但总是迟迟不开始。',assistant:'我能理解这种状态。事情很多、想法也不少，但真正开始时又像被什么拦住了。\n\n我不想急着把它归结为缺乏自律。也许我们可以先看看：这些事情里，哪些是你真正想做的，哪些只是觉得自己应该做？'},
    {user:'你觉得我最近的状态可能是什么原因？',assistant:'从刚才的表达来看，我有一个暂时的观察：你可能不是没有行动意愿，而是同时面对太多方向时，很难判断从哪里开始。\n\n这只是一个待验证的理解，不一定准确。你觉得它和你的实际感受接近吗？'}
  ];
  let last='';
  for(const turn of sample){
    last=appendDateIfNeeded(history,{created_at:new Date().toISOString()},last);
    const group=document.createElement('div');group.className='turn-group';
    group.append(createMessage('user',turn.user,null,new Date().toISOString()).row);
    group.append(createMessage('assistant',turn.assistant,null,new Date().toISOString()).row);
    history.append(group);
  }
  const insight=document.createElement('section');insight.className='inline-card insight-card';
  const icon=document.createElement('div');icon.className='inline-card-icon insight-icon';icon.textContent='✧';
  const content=document.createElement('div');content.className='inline-card-content';
  const title=document.createElement('strong');title.textContent='一个关于你的观察';
  const copy=document.createElement('p');copy.textContent='你可能更容易在方向清晰、一次只关注一件事的时候开始行动。这是一个暂时的观察，不是对你的定论。';
  const tag=document.createElement('span');tag.className='soft-tag';tag.textContent='待验证';
  content.append(title,copy,tag);
  const actions=document.createElement('div');actions.className='inline-card-actions';
  for(const label of ['认可','部分认可','不太准确'])actions.append(makeButton(label,'subtle-button',()=>{tag.textContent=label==='不太准确'?'已否定':label==='部分认可'?'部分认可':'已认可';toast('示例交互，不会写入个人认识');}));
  insight.append(icon,content,actions);history.append(insight);

  const tasks=document.createElement('section');tasks.className='inline-card task-card';
  const taskIcon=document.createElement('div');taskIcon.className='inline-card-icon';taskIcon.textContent='☷';
  const taskContent=document.createElement('div');taskContent.className='inline-card-content';
  const taskTitle=document.createElement('strong');taskTitle.textContent='你今天的任务（示例）';
  const list=document.createElement('div');list.className='demo-task-list';
  for(const label of ['整理项目资料','阅读 30 分钟','出门散步']){
    const row=document.createElement('label');row.className='demo-task';
    const checkbox=document.createElement('input');checkbox.type='checkbox';
    const span=document.createElement('span');span.textContent=label;row.append(checkbox,span);list.append(row);
  }
  taskContent.append(taskTitle,list);
  const taskFoot=document.createElement('div');taskFoot.className='inline-card-foot';taskFoot.textContent='这些是界面示例，并非你的真实任务';
  taskContent.append(taskFoot);tasks.append(taskIcon,taskContent);history.append(tasks);

  const record=document.createElement('section');record.className='inline-card record-card';
  const recordIcon=document.createElement('div');recordIcon.className='inline-card-icon record-icon';recordIcon.textContent='▤';
  const recordContent=document.createElement('div');recordContent.className='inline-card-content';
  const recordTitle=document.createElement('strong');recordTitle.textContent='要把这段经历记录下来吗？';
  const recordText=document.createElement('p');recordText.textContent='以后回看时，也许能帮你重新理解今天的自己。';
  recordContent.append(recordTitle,recordText);
  const recordActions=document.createElement('div');recordActions.className='inline-card-actions';
  recordActions.append(makeButton('暂不保存','subtle-button',()=>toast('已暂时关闭示例卡片')));
  recordActions.append(makeButton('保存示例记录','primary-small',()=>toast('示例交互，不会保存真实记录')));
  record.append(recordIcon,recordContent,recordActions);history.append(record);
  history.scrollTop=history.scrollHeight;
}
async function updateStatus(){
  try{
    const status=await api('/api/status');$('connection-indicator').classList.add('connected');
    const instruction=status.sessionInstruction?.active;
    $('connection-label').textContent=instruction?'本地智能体已连接 · 指令已固定':'本地智能体已连接';
    const jobs=status.jobs||{};$('connection-label').title='后台整理任务：'+(jobs.pending||0)+' 项等待中'+(instruction?'；本次会话已固定自定义指令（'+status.sessionInstruction.characters+' 字）':'');
  }catch{
    $('connection-indicator').classList.remove('connected');$('connection-label').textContent='本地服务暂不可用';
  }
}
async function searchHistory(){
  const q=$('search-query').value.trim();
  if(!q){$('search-summary').textContent='请输入要搜索的关键词';return;}
  $('search-summary').textContent='正在搜索…';$('search-results').replaceChildren();
  const params=new URLSearchParams({q});
  if($('search-from').value)params.set('from',$('search-from').value);
  if($('search-to').value)params.set('to',$('search-to').value);
  try{
    const {results}=await api('/api/search?'+params.toString());
    $('search-summary').textContent=results.length?'找到 '+results.length+' 条相关记录':'没有找到相关记录';
    for(const result of results){
      const button=document.createElement('button');button.type='button';button.className='search-result';
      const snippet=document.createElement('span');snippet.className='search-result-snippet';
      const query=q.toLocaleLowerCase(),text=(result.user||'').toLocaleLowerCase().includes(query)?result.user:result.assistant;
      snippet.textContent=text.length>150?text.slice(0,150)+'…':text;
      const meta=document.createElement('small');meta.textContent=dateLabel(result.created_at)+' · '+formatTime(result.created_at);
      button.append(snippet,meta);
      button.addEventListener('click',async()=>{
        $('search-dialog').close();
        try{await loadHistory({scroll:false,around:result.id});}catch(error){toast(error.message);}
      });
      $('search-results').append(button);
    }
  }catch(error){$('search-summary').textContent=error.message;}
}

$('chat-form').addEventListener('submit',event=>{event.preventDefault();sendMessage();});
$('message').addEventListener('input',resizeComposer);
$('message').addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendMessage();}
});
$('stop-button').addEventListener('click',()=>state.controller?.abort());
$('load-older').addEventListener('click',()=>void loadOlder());
$('search-open').addEventListener('click',()=>{$('search-dialog').showModal();$('search-query').focus();});
$('search-close').addEventListener('click',()=>$('search-dialog').close());
$('search-form').addEventListener('submit',event=>{event.preventDefault();void searchHistory();});
$('demo-open').addEventListener('click',showDemo);
$('demo-exit').addEventListener('click',()=>{state.demo=false;$('demo-notice').hidden=true;void loadHistory({scroll:true});});
document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>{
  $('message').value=button.dataset.prompt;resizeComposer();$('message').focus();
}));
document.querySelectorAll('[data-nav]').forEach(button=>button.addEventListener('click',()=>{
  if(button.dataset.nav!=='friend')toast('这个空间将在后续阶段开放');
}));
$('settings-button').addEventListener('click',()=>toast('设置页面将在后续阶段开放'));
$('more-button').addEventListener('click',()=>toast('这是你的单一长期会话，不需要创建新聊天'));
$('theme-toggle').addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
setTheme(localStorage.getItem('becoming-theme')||'light');
resizeComposer();
loadHistory({scroll:true}).catch(error=>toast(error.message));
void updateStatus();
setInterval(()=>void updateStatus(),15000);
