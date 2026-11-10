const fs=require('fs'),vm=require('vm'),assert=require('assert');
const saved=new Map();
const storage={getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)};
const legacySaved=new Map();
const legacyStorage={getItem:k=>legacySaved.get(k)||null,setItem:(k,v)=>legacySaved.set(k,v),removeItem:k=>legacySaved.delete(k)};
class Node {
  get isConnected(){return !!this.parent;}
  get lastElementChild(){return this.children.at(-1)||null;}
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
let agentEnabled=false,routerEnabled=false;
const agentRequests=[];
let agentResult={task_id:'a'.repeat(32),task_revision:0,status:'needs_input',response:'Supplier aur date batayein.'};
const purchaseRequests=[];let purchaseConflict=false;
const conversations=new Map();let chatCounter=0;
const ownChats=()=>[...conversations.values()].filter(chat=>!chat.deleted&&chat.user_id===scope?.user_id&&chat.organization_id===scope?.organization_id).reverse();
const setServerMessages=messages=>{const chat=ownChats()[0];if(chat){chat.messages=messages;chat.revision++;}};
function page(sessionStorage=legacyStorage){
  const timers=[];
  const nodes=new Map(),events={};const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  get('authModal').classes.add('hidden');
  const document={getElementById:get,querySelectorAll:()=>[],addEventListener(){},createElement:tag=>{const n=new Node();n.tag=tag;return n;}};
  const window={crypto:require('node:crypto').webcrypto,localStorage:storage,sessionStorage,getBusinessChatScope:()=>scope,addEventListener:(k,fn)=>events[k]=fn,
    createBusinessVoice:()=>({cancel(){},toggle(){}}),
    fetchWithAuth:async(url,options={})=>{
      requests.push(url);let value;
      const prefix='/api/v1/business/conversations';
      if(url.endsWith('/task-capabilities')){value={enabled:agentEnabled,router_enabled:routerEnabled};
      }else if(url.startsWith('/api/v1/business/tasks/')){value=agentResult;
      }else if(agentEnabled&&url.endsWith('/command')){
        agentRequests.push(JSON.parse(options.body));value=agentResult;
      }else if(url.includes('/purchase-drafts/')&&url.endsWith('/chat')){
        const body=JSON.parse(options.body);purchaseRequests.push(body);
        if(purchaseConflict&&!body.resume){purchaseConflict=false;return {ok:false,status:409,json:async()=>({detail:'Stale draft'})};}
        value={response:'Invoice number kya hai?',purchase_assistant:{draft_id:'purchase-test',revision:8,field:'invoice_number',choices:[]}};
      }else if(url===prefix&&options.method==='POST'){
        value={id:(++chatCounter).toString(16).padStart(32,'0'),title:'New chat',revision:0,messages:[],user_id:scope.user_id,organization_id:scope.organization_id,session_id:scope.session_id};conversations.set(value.id,value);
      }else if(url===prefix){value={conversations:ownChats().map(chat=>({...chat}))};
      }else if(url.startsWith(prefix+'/')){
        const path=url.split('?')[0];
        const chat=conversations.get(path.slice(prefix.length+1).replace(/\/restore$/,''));
        if(!chat||chat.user_id!==scope.user_id||chat.organization_id!==scope.organization_id)return {ok:false,json:async()=>({detail:'Chat nahi mili'})};
        if(options.method==='DELETE'){
          assert.equal(Number(url.split('revision=')[1]),chat.revision);chat.deleted=true;chat.revision++;value={id:chat.id,revision:chat.revision,deleted:true};
        }else if(path.endsWith('/restore')){
          assert.equal(JSON.parse(options.body).revision,chat.revision);chat.deleted=false;chat.revision++;value={...chat};
        }else if(chat.deleted){return {ok:false,status:404,json:async()=>({detail:'Chat nahi mili'})};
        }else if(options.method==='PUT'){
          const body=JSON.parse(options.body);assert.equal(body.revision,chat.revision,'saves use current server revision');
          chat.messages=body.messages;chat.revision++;chat.session_id=scope.session_id;chat.title=body.messages.find(message=>message.role==='user')?.text||'New chat';value={...chat};
        }else{
          value=JSON.parse(JSON.stringify(chat));
          if(value.session_id!==scope.session_id)for(const message of value.messages)if(message.data?.preview)message.data.preview.can_confirm=false;
        }
      }else value=url.endsWith('/reconcile')?{response:'Voucher 4 verified',sync_status:'verified'}:{response:'Report ready',mcp_report:{rows:[['October','₹5,950.00']]}};
      return {ok:true,json:async()=>JSON.parse(JSON.stringify(value))};
    },
    renderBusinessTally:(tools,data,callbacks)=>{window.agentCallbacks=callbacks;(window.taskCallbacks||=[]).push({data,callbacks});if(data.tally_action){callbacks.updateState?.(data);callbacks.updateMessage?.(data.response);}if(data.mcp_report){const p=new Node();p.textContent=JSON.stringify(data.mcp_report.rows);tools.append(p);}}
  };
  const context={window,document,setTimeout:fn=>timers.push(fn),clearTimeout(){},MutationObserver:class{observe(){}},URL:{revokeObjectURL(){}},AbortController,FormData:class{},console};
  vm.runInNewContext(fs.readFileSync('app/web/business-chat-store.js','utf8'),context);
  vm.runInNewContext(fs.readFileSync('app/web/business-chat.js','utf8'),context);
  return {get,events,window,timers};
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
  corrupt.get('businessChatList').children[1].children[0].listeners.click();await flush();
  assert.equal(corrupt.get('businessMessages').children.length,1,'old chat reopens from the sidebar');
  assert.equal(requests.filter(url=>url.endsWith('/command')).length,beforeReopen,'reopening does not replay a command');
  saved.clear();const freshBrowser=page(emptyTabStorage);await flush();
  assert.equal(freshBrowser.get('businessChatList').children.length,2,'server chats survive clearing browser storage');
  setServerMessages([{role:'assistant',text:'Rate kya hai?',data:{purchase_assistant:{draft_id:'purchase-test',revision:7,field:'0:rate',choices:[]}}}]);
  let purchasePage=page(emptyTabStorage);await flush();
  purchasePage.get('businessInput').value='350';purchasePage.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  const sent=purchaseRequests.at(-1);
  assert.equal(sent.revision,7);assert.equal(sent.expected_revision,7);assert.equal(sent.field,'0:rate');assert.equal(sent.message,'350');
  assert.match(sent.request_id,/^[a-f0-9-]{36}$/,'message has idempotency identity');
  purchasePage=page(emptyTabStorage);await flush();
  purchaseConflict=true;purchasePage.get('businessInput').value='INV-1';purchasePage.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.deepEqual(purchaseRequests.at(-1),{resume:true},'stale answer refreshes state without replaying mutation');
  const beforeTopic=purchaseRequests.length;
  purchasePage.get('businessInput').value='Cement stock kitna hai';purchasePage.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.equal(purchaseRequests.length,beforeTopic,'new stock topic is not consumed as an invoice answer');
  setServerMessages([{role:'assistant',text:'History pending',data:{draft_id:'purchase-test',purchase_context:{native_history_status:'queued'},purchase_assistant:{draft_id:'purchase-test',revision:8,field:'0:rate',choices:[]}}}]);
  const historyPage=page(emptyTabStorage);await flush();
  assert.equal(historyPage.timers.length,1,'queued native history schedules a bounded refresh');
  const historyMessageCount=historyPage.get('businessMessages').children.length;
  await historyPage.timers.shift()();await flush();
  assert.deepEqual(purchaseRequests.at(-1),{resume:true},'history polling only resumes read state');
  assert.equal(historyPage.get('businessMessages').children.length,historyMessageCount,'history result updates same message');
  assert.equal(historyPage.get('businessMessages').lastElementChild.chatRecord.text,'Invoice number kya hai?');
  setServerMessages([{role:'assistant',text:'History pending',data:{draft_id:'purchase-test',purchase_context:{native_history_status:'processing'},purchase_assistant:{draft_id:'purchase-test',revision:8,field:'0:rate',choices:[]}}}]);
  const interruptedPage=page(emptyTabStorage);await flush();
  interruptedPage.get('businessInput').value='Cement stock kitna hai';interruptedPage.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  const beforeInterruptedPoll=purchaseRequests.length;
  await interruptedPage.timers.shift()();await flush();
  assert.equal(purchaseRequests.length,beforeInterruptedPoll,'new user message prevents stale history overwrite');
  const deletePage=page(emptyTabStorage);await flush();
  const originalCount=ownChats().length;
  const commandsBeforeDelete=requests.filter(url=>url.endsWith('/command')).length;
  const selectedBefore=JSON.parse(storage.getItem('philixa:chat:v2:'+JSON.stringify(['u1','o1'])+':selected'));
  const rows=deletePage.get('businessChatList').children;
  const selectedRow=rows.find(row=>row.children[0]?.textContent===conversations.get(selectedBefore)?.title);
  assert(selectedRow,'selected chat is shown as a formatted row');
  assert.equal(selectedRow.children[1].title,'Delete chat');
  await selectedRow.children[1].listeners.click();await flush();
  assert.equal(ownChats().length,originalCount-1);
  assert.equal(deletePage.get('businessMessages').children.length,0,'deleting selected chat clears its transcript');
  assert(conversations.get(selectedBefore).messages.length,'soft delete retains stored messages');
  await deletePage.get('businessChatList').children[0].children[1].listeners.click();await flush();
  assert.equal(ownChats().length,originalCount,'Undo restores the conversation');
  assert(deletePage.get('businessMessages').children.length,'Undo reopens saved messages');
  assert.equal(requests.filter(url=>url.endsWith('/command')).length,commandsBeforeDelete,'delete and Undo never replay accounting commands');
  conversations.get(selectedBefore).deleted=true; // Another tab deleted this selected chat.
  const createdBefore=chatCounter;const afterExternalDelete=page(emptyTabStorage);await flush();
  assert.equal(afterExternalDelete.get('businessMessages').children.length,0,'stale browser copy does not resurrect deleted chat');
  assert.equal(chatCounter,createdBefore,'no replacement conversation is silently created');
  agentEnabled=true;
  const agentPage=page(emptyTabStorage);await flush();
  agentPage.get('businessInput').value='Prepare a purchase draft';
  agentPage.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.match(agentRequests.at(-1).request_id,/^[a-f0-9-]{36}$/);
  agentPage.get('businessInput').value='Sharma Traders';
  agentPage.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.equal(agentRequests.at(-1).task_id,'a'.repeat(32));
  assert.equal(agentRequests.at(-1).expected_revision,0);
  const beforeInline=agentPage.get('businessMessages').children.length;
  await agentPage.window.agentCallbacks.submit('Sharma Traders',false,{selection:{reference:'f'.repeat(64),draft_revision:0,evidence_version:'test'}});await flush();
  assert.equal(agentPage.get('businessMessages').children.length,beforeInline,'task selection updates existing card without extra chat bubbles');
  assert.equal(agentRequests.at(-1).task_id,'a'.repeat(32));
  assert.equal(agentRequests.at(-1).selection.reference,'f'.repeat(64));
  setServerMessages([{role:'assistant',text:'Queued',data:{...agentResult,status:'queued'}}]);
  const queuedPage=page(emptyTabStorage);await flush();
  const countBeforePoll=agentRequests.length;
  agentResult={...agentResult,response:'Draft ready for review.'};
  await queuedPage.timers.at(-1)();await flush();
  assert.equal(queuedPage.get('businessMessages').children[0].querySelector('.business-message-text').textContent,'Draft ready for review.');
  assert.equal(agentRequests.length,countBeforePoll,'restore/poll reads task state without replaying command');
  setServerMessages([{role:'assistant',text:'Supplier?',data:{...agentResult,status:'needs_input',
    draft_id:'purchase-test',purchase_context:{native_history_status:'pending'},
    purchase_assistant:{draft_id:'purchase-test',revision:1,field:'party_name',choices:['Sharma Traders']}}}]);
  const taskHistoryPage=page(emptyTabStorage);await flush();
  assert.equal(taskHistoryPage.timers.length,0,'task history never calls legacy chat polling and loses durable task identity');
  routerEnabled=true;
  setServerMessages([{role:'assistant',text:'Rate kya hai?',data:{purchase_assistant:{draft_id:'purchase-test',revision:7,field:'0:rate'}}}]);
  const routerPage=page(emptyTabStorage);await flush();
  const beforeLegacy=purchaseRequests.length;
  routerPage.get('businessInput').value='tu mere liye kya kar sakti hai';
  routerPage.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.equal(purchaseRequests.length,beforeLegacy,'free text must not be sent to legacy draft endpoint by browser guess');
  assert.equal(agentRequests.at(-1).text,'tu mere liye kya kar sakti hai');
  setServerMessages([{role:'assistant',text:'Bill question?',data:{...agentResult,document_task:true}}]);
  const semanticPage=page(emptyTabStorage);await flush();
  semanticPage.get('businessInput').value='Can you describe the work you support?';
  semanticPage.get('businessComposer').listeners.submit({preventDefault(){}});await flush();
  assert.equal(agentRequests.at(-1).task_id,undefined,'semantic routing owns free-text task selection, not last assistant');
  assert.ok(agentRequests.at(-1).conversation_id,'server receives conversation context for routing');
  assert.equal(agentRequests.at(-1).candidate_task_id,'a'.repeat(32),'legacy task is a context hint only, never an automatic resume');
  setServerMessages([{role:'assistant',text:'Old task',data:{...agentResult,task_id:'b'.repeat(32),task_revision:4}},
    {role:'assistant',text:'New task',data:{...agentResult,task_id:'c'.repeat(32),task_revision:9}}]);
  const cardsPage=page(emptyTabStorage);await flush();
  const oldCard=cardsPage.window.taskCallbacks.find(entry=>entry.data.task_id==='b'.repeat(32));
  await oldCard.callbacks.submit('Refresh current card',false,{context_refresh:true});await flush();
  assert.equal(agentRequests.at(-1).task_id,'b'.repeat(32),'explicit card action targets its own task, never most recent task');
  assert.equal(agentRequests.at(-1).expected_revision,4);
  setServerMessages([{role:'assistant',text:'Worker unavailable',data:{...agentResult,status:'queued',progress_active:false}}]);
  const offlinePage=page(emptyTabStorage);await flush();
  assert.equal(offlinePage.get('businessMessages').children[0].querySelector('.business-thinking'),null,'no fake thinking animation when worker is unavailable');
  console.log('PASS: chat restore/scope safety plus task creation/resume identity and status-only task polling');
})().catch(e=>{console.error(e);process.exitCode=1;});
