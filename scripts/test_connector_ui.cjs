// Exercise the actual onboarding script in a small DOM harness.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map(),intervals=[],requests=[];
class Node {
  constructor(){this.hidden=false;this.value="";this.style={};this.dataset={};this.listeners={};this.lastChild={textContent:''};this.elements={company:new NodeControl(),code:{value:'',focus(){}},replace:{checked:false}};this.classList={contains:()=>true};}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this[name]=value;}
  append(...children){this.children=(this.children||[]).concat(children);}
  querySelector(){return {disabled:false};} replaceChildren(...children){this.children=children;} reset(){} close(){} click(){return this.listeners.click?.();}
}
class NodeControl {addEventListener(){}replaceChildren(){} }
const node=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
let status={paired:true,online:false,connection_state:'connector_offline',can_configure:true,companies:[],installer_url:'/api/v1/integrations/tally/helper/download'};
const document={hidden:false,getElementById:node,addEventListener(){},createElement:()=>new Node()};
const window={fetchWithAuth:async(url,opts)=>{
  requests.push([url,opts]);return {ok:true,json:async()=>url.endsWith('/helper/status')?structuredClone(status):url.endsWith('/setup/check')?{...status,connection_state:'live_available'}:{configured:false,can_configure:true}};
}};
const context={window,document,MutationObserver:class{observe(){}},setInterval:fn=>intervals.push(fn),setTimeout(){},URL,Date,FormData:class{}};
vm.runInNewContext(fs.readFileSync('app/web/business-tally.js','utf8'),context);
async function flush(){for(let i=0;i<12;i++)await Promise.resolve();}
(async()=>{
  await flush();node('businessConnections').open=true;await window.openBusinessTally();
  assert.equal(node('tallyDownload').hidden,false,'paired offline PC must retain download');
  assert.match(node('tallyReadStatus').textContent,/Windows Start/);
  status={...status,online:true,connection_state:'tally_closed'};await intervals[0]();await flush();
  assert.match(node('businessConnectionTop').lastChild.textContent,/Tally closed/,'open dialog must refresh badge');
  assert.match(node('tallyReadStatus').textContent,/automatically/);
  await node('tallyVerifySetup').listeners.click();await flush();
  assert.match(node('tallyReadStatus').textContent,/Live stock access verified/);
  status={...status,connection_state:'checking'};node('tallyPairForm').hidden=false;node('tallyPairForm').elements.code.value='KEEP-MY-DRAFT';
  await intervals[0]();await flush();assert.equal(node('tallyPairForm').elements.code.value,'KEEP-MY-DRAFT','refresh must not reset code form');
  let recursivePreviews=0;
  const callbacks={submit(){},toolButton(){},connect(){},renderResult(){recursivePreviews++;}};
  window.renderBusinessTally(new Node(),{tally_action:'draft',preview:{can_confirm:false}},callbacks);
  assert.equal(recursivePreviews,0,'preview action must not recursively render another preview/status panel');
  let statusClick;
  const actionTools=new Node();
  window.renderBusinessTally(actionTools,{tally_action:'queued',sync_status:'queued',response:'Still queued'},
    {...callbacks,toolButton(panel,label,fn){if(label==='Status check (no resend)')statusClick=fn;}});
  const panel=actionTools.children[0],message=panel.children[0];
  assert.equal(message.textContent,'Still queued','initial action status must be visible');
  window.fetchWithAuth=async()=>{throw new Error('Network unavailable');};
  await statusClick();
  assert.equal(message.textContent,'Network unavailable','status errors must be attached to the visible panel');
  const chatMessage=new Node(),controls=new Node();
  const buttonCallbacks={...callbacks,updateMessage(text){chatMessage.textContent=text;return chatMessage;},
    toolButton(parent,label,fn){const button=new Node();button.textContent=label;button.click=fn;parent.append(button);}};
  window.renderBusinessTally(controls,{tally_action:'approved',sync_status:'queued',response:'Sync pending'},buttonCallbacks);
  const actionPanel=controls.children[0];
  assert.equal(chatMessage.textContent,'Sync pending');
  assert.equal(actionPanel.children.length,2,'status must not be duplicated below the chat message');
  const check=actionPanel.children.find(n=>n.textContent==='Status check (no resend)');
  window.fetchWithAuth=async()=>({ok:true,json:async()=>({response:'Voucher 4 verified',sync_status:'verified'})});
  await check.click();
  assert.equal(chatMessage.textContent,'Voucher 4 verified','pending text must be replaced in the original chat message');
  assert.equal(actionPanel.children.length,0,'verified action must remove cancel and status controls');
  await check.click();
  assert.equal(chatMessage.textContent,'Voucher 4 verified');
  assert.equal(controls.children.length,1,'repeated checks must not append messages or status panels');
  const reportTools=new Node();
  window.renderBusinessTally(reportTools,{mcp_report:{title:'Purchase register — monthly summary',company:'Philixa Test',read_at:'2026-10-11T10:00:00Z',total_rows:1,columns:['Month','Debit amount'],rows:[['October','₹5,950.00']],arguments:{from:'01-10-2026',to:'02-10-2026'},note:'Monthly summary'}},callbacks);
  const reportPanel=reportTools.children[0];
  assert.equal(reportPanel.children[1].textContent,'Purchase register — monthly summary');
  assert.equal(reportPanel.children[2].textContent,'Date range: 01-10-2026 to 02-10-2026');
  console.log('PASS: setup, action status, readable report title and exact date range');
})().catch(error=>{console.error(error);process.exitCode=1;});


