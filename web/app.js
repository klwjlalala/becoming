const $=id=>document.getElementById(id);
let conversation='default',pending=null,busy=false,refreshVersion=0;
async function api(path,options){const res=await fetch(path,options),data=await res.json();if(!res.ok)throw Error(data.error||'请求失败');return data;}
const post=(path,data)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function add(role,text){const el=document.createElement('article');el.className='turn '+role;const label=document.createElement('b');label.textContent=role==='user'?'我':'Becoming';el.append(label,document.createTextNode(text));$('history').append(el);}
async function conversations(){const {conversations}=await api('/api/conversations');$('conversation').replaceChildren(...conversations.map(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=c.title;return o;}));$('conversation').value=conversation;}
async function refresh(){const id=conversation,version=++refreshVersion,{turns,pending_growth}=await api('/api/history?conversation_id='+encodeURIComponent(id));if(id!==conversation||version!==refreshVersion)return;$('history').replaceChildren();for(const t of turns){add('user',t.user);add('assistant',t.assistant);}pending=pending_growth;$('confirmation').hidden=!pending;}
async function status(){try{const s=await api('/api/status');$('status').textContent='本地智能体 · 后台待处理 '+(s.jobs.pending||0)+' · 处理中 '+(s.jobs.running||0)+(s.jobs.failed?' · 失败 '+s.jobs.failed:'');}catch{$('status').textContent='运行时不可用';}}
function lock(v){busy=v;for(const id of ['send','conversation','new-conversation','confirm','cancel'])$(id).disabled=v;}
async function send(text,clear=false){if(!text||busy)return;lock(true);$('error').textContent='';try{const {turn}=await post('/api/chat',{text,conversation_id:conversation});if(clear)$('message').value='';await refresh();if(!turn.id)add('assistant',turn.assistant);}catch(e){$('error').textContent=e.message;}finally{lock(false);void status();}}
$('chat').addEventListener('submit',e=>{e.preventDefault();void send($('message').value.trim(),true);});
$('confirm').onclick=()=>{if(pending)void send('/confirm '+pending.token);};
$('cancel').onclick=()=>void send('/cancel');
$('conversation').onchange=()=>{conversation=$('conversation').value;pending=null;$('confirmation').hidden=true;refresh().catch(e=>$('error').textContent=e.message);};
$('new-conversation').onclick=async()=>{if(busy)return;lock(true);try{const {conversation:c}=await post('/api/conversations',{title:'新会话'});conversation=c.id;await conversations();await refresh();}catch(e){$('error').textContent=e.message;}finally{lock(false);}};
(async()=>{await conversations();await refresh();})().catch(e=>$('error').textContent=e.message);
void status();setInterval(()=>{void status();if(!busy)refresh().catch(()=>{});},5000);
