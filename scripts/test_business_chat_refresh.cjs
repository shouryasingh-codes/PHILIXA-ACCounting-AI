const fs=require('fs'),vm=require('vm'),assert=require('assert');
const saved=new Map();
const storage={getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)};
const legacySaved=new Map();
const legacyStorage={getItem:k=>legacySaved.get(k)||null,setItem:(k,v)=>legacySaved.set(k,v),removeItem:k=>legacySaved.delete(k)};
class Node {
  constructor(){this.children=[];this.listeners={};this.style={};this.value='';this.scrollHeight=100;this.textContent='';this.className='';this.hidden=false;this.classes=new Set();this.classList={contains:x=>this.classes.has(x),remove:x=>this.classes.delete(x),toggle:x=>{if(this.classes.has(x))this.classes.delete(x);else this.classes.add(x);}};}
  append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
  replaceChildren(...nodes){this.children=[];this.append(...nodes);}
  remove(){this.parent.children=this.parent.children.filter(n=>n!==this);}
  setAttribute(){} addEventListener(k,fn){this.listeners[k]=fn;} focus(){} pause(){}
  querySelectorAll(s){return this.children.flatMap(n=>[...(s.startsWith('.')?n.className.split(' ').includes(s.slice(1)):n.tag===s)?[n]:[],...n.querySelectorAll(s)]);}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
}
let scope={user_id:'u1',organization_id:'o1',session_id:'s1'};
const requests=[];
const conversations=new Map();let chatCounter=0;
const ownChats=()=>[...conversations.values()].filter(chat=>chat.user_id===scope?.user_id&&chat.organization_id===scope?.organization_id).reverse();
const setServerMessages=messages=>{const chat=ownChats()[0];if(chat){chat.messages=messages;chat.revision++;}};
function page(sessionStorage=legacyStorage){
  const nodes=new Map(),events={};const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  get('authModal').classes.add('hidden');
  const document={getElementById:get,querySelectorAll:()=>[],addEventListener(){},createElement:tag=>{const n=new Node();n.tag=tag;return n;}};
  const window={localStorage:storage,sessionStorage,getBusinessChatScope:()=>scope,addEventListener:(k,fn)=>events[k]=fn,
    createBusinessVoice:()=>({cancel(){},toggle(){}}),
    fetchWithAuth:async(url,options={})=>{
      requests.push(url);let value;
      const prefix='/api/v1/business/conversations';
      if(url===prefix&&options.method==='POST'){
        value={id:'chat'+(++chatCounter),title:'New chat',revision:0,messages:[],user_id:scope.user_id,organization_id:scope.organization_id,session_id:scope.session_id};conversations.set(value.id,value);
      }else if(url===prefix){value={conversations:ownChats().map(chat=>({...chat}))};
      }else if(url.startsWith(prefix+'/')){
        const chat=conversations.get(url.slice(prefix.length+1));
        if(!chat||chat.user_id!==scope.user_id||chat.organization_id!==scope.organization_id)return {ok:false,json:async()=>({detail:'Chat nahi mili'})};
        if(options.method==='PUT'){
          const body=JSON.parse(options.body);assert.equal(body.revision,chat.revision,'saves use current server revision');
          chat.messages=body.messages;chat.revision++;chat.session_id=scope.session_id;chat.title=body.messages.find(message=>message.role==='user')?.text||'New chat';value={...chat};
        }else{
          value=JSON.parse(JSON.stringify(chat));
          if(value.session_id!==scope.session_id)for(const message of value.messages)if(message.data?.preview)message.data.preview.can_confirm=false;
        }
      }else value=url.endsWith('/reconcile')?{response:'Voucher 4 verified',sync_status:'verified'}:{response:'Report ready',mcp_report:{rows:[['October','₹5,950.00']]}};
      return {ok:true,json:async()=>JSON.parse(JSON.stringify(value))};
    },
    renderBusinessTally:(tools,data,callbacks)=>{if(data.tally_action){callbacks.updateState?.(data);callbacks.updateMessage?.(data.response);}if(data.mcp_report){const p=new Node();p.textContent=JSON.stringify(data.mcp_report.rows);tools.append(p);}}
  };
  const context={window,document,MutationObserver:class{observe(){}},URL:{revokeObjectURL(){}},AbortController,FormData:class{},console};
  vm.runInNewContext(fs.readFileSync('app/web/business-chat-store.js','utf8'),context);
  vm.runInNewContext(fs.readFileSync('app/web/business-chat.js','utf8'),context);
  return {get,events,window};
}
async function flush(){for(let i=0;i<150;i++)await Promise.resolve();}
(async()=>{
  let p=page();await flush();p.get('businessInput').value='Purchase report dikhao';
  p.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.equal(p.get('businessMessages').children.length,2);
  p.events.pagehide();
  let reloaded=page();await flush();
  assert.equal(reloaded.get('businessMessages').children.length,2,'refresh restores both messages');
  assert.equal(reloaded.get('businessMessages').children[0].querySelector('.business-message-text').textContent,'Purchase report dikhao');
  assert.ok(reloaded.get('businessMessages').children[1].querySelector('.business-tools').children[0].textContent.includes('5,950.00'),'report data restored');
  assert.equal(requests.filter(x=>x.endsWith('/command')).length,1,'refresh must not replay a command');
  const emptyTabStorage={getItem:()=>null,setItem(){},removeItem(){}};
  const reopened=page(emptyTabStorage);await flush();
  assert.equal(reopened.get('businessMessages').children.length,2,'new tab restores durable browser chat');
  const store=p.window.createBusinessChatStore(storage);store.scope(scope);
  store.write([{role:'assistant',text:'Pending',data:{tally_action:'token4',response:'Pending',sync_status:'queued'}}]);
  setServerMessages([{role:'assistant',text:'Pending',data:{tally_action:'token4',response:'Pending',sync_status:'queued'}}]);
  reloaded=page();await flush();
  assert.equal(reloaded.get('businessMessages').children[0].querySelector('.business-message-text').textContent,'Voucher 4 verified','restored action gets latest status');
  assert.equal(requests.filter(x=>x.endsWith('/confirm')).length,0,'restore never confirms writes');
  scope={...scope,organization_id:'o2'};const other=page();await flush();
  assert.equal(other.get('businessMessages').children.length,0,'other workspace does not see this chat');
  scope={...scope,organization_id:'o1',user_id:'u2'};assert.equal(page().get('businessMessages').children.length,0,'other user does not see this chat');
  scope={user_id:'u1',organization_id:'o1',session_id:'s1'};
  const oldPreview={role:'assistant',text:'Purchase preview',data:{preview:{token:'old-token',can_confirm:true,lines:[]}}};
  store.scope(scope);store.write([oldPreview]);
  setServerMessages([oldPreview]);
  scope={...scope,session_id:'s2'};
  const nextLogin=p.window.createBusinessChatStore(storage);nextLogin.scope(scope);
  assert.equal(nextLogin.read()[0].data.preview.can_confirm,false,'old login preview remains visible but cannot approve');
  scope=null;const pendingAuth=page();await flush();
  pendingAuth.get('businessInput').value='do not send without a session';
  const beforeAuth=requests.length;pendingAuth.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.equal(requests.length,beforeAuth,'missing auth scope cannot silently create unsaved chat');
  scope={user_id:'u1',organization_id:'o1',session_id:'s2'};pendingAuth.events['business-auth-ready']();await flush();
  assert.equal(pendingAuth.get('businessMessages').children.length,1,'late auth bootstrap restores existing conversation');
  // A pre-update same-tab transcript is migrated without losing messages.
  scope={user_id:'legacy-user',organization_id:'legacy-org',session_id:'legacy-session'};
  legacyStorage.setItem('philixa:chat:v1:'+JSON.stringify(['legacy-user','legacy-org','legacy-session']),JSON.stringify({version:1,messages:[{role:'user',text:'Saved before update'}]}));
  const migrated=page();await flush();
  assert.equal(migrated.get('businessMessages').children.length,1,'legacy same-tab messages migrate');
  assert.ok(saved.has('philixa:chat:v2:'+JSON.stringify(['legacy-user','legacy-org'])),'migration saves durable copy');
  scope={user_id:'u1',organization_id:'o1',session_id:'s1'};reloaded=page();await flush();
  reloaded.get('businessNewChat').listeners.click();await flush();reloaded.events.pagehide();
  assert.equal(page().get('businessMessages').children.length,0,'New chat remains empty after refresh');
  storage.setItem('philixa:chat:v2:'+JSON.stringify(['u1','o1']),'{broken');const corrupt=page();await flush();assert.equal(corrupt.get('businessMessages').children.length,0,'corrupt storage cannot break page');
  assert.equal(corrupt.get('businessChatList').children.length,1,'New chat retains previous sidebar conversation');
  corrupt.get('businessInput').value='Second chat';corrupt.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.equal(corrupt.get('businessChatList').children.length,2,'separate conversations are listed');
  const beforeReopen=requests.filter(url=>url.endsWith('/command')).length;
  corrupt.get('businessChatList').children[1].listeners.click();await flush();
  assert.equal(corrupt.get('businessMessages').children.length,1,'old chat reopens from the sidebar');
  assert.equal(requests.filter(url=>url.endsWith('/command')).length,beforeReopen,'reopening does not replay a command');
  saved.clear();const freshBrowser=page(emptyTabStorage);await flush();
  assert.equal(freshBrowser.get('businessChatList').children.length,2,'server chats survive clearing browser storage');
  console.log('PASS: reload/new tab, delayed auth, legacy migration, cross-login preview safety, report/status restore, no write replay, scope isolation, New chat and corrupt storage');
})().catch(e=>{console.error(e);process.exitCode=1;});
