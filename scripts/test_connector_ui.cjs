// Exercise the actual onboarding script in a small DOM harness.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map(),intervals=[],requests=[];
class Node {
  constructor(){this.hidden=false;this.value="";this.style={};this.dataset={};this.listeners={};this.lastChild={textContent:''};this.elements={company:new NodeControl(),godown:new NodeControl(),purchase_ledger:new NodeControl(),sales_ledger:new NodeControl(),test_company:{checked:false},code:{value:'',focus(){}},replace:{checked:false}};this.elements.namedItem=key=>this.elements[key];this.classList={contains:()=>true,add(){},remove(){}};}
  addEventListener(name,fn){this.listeners[name]=fn;}
  setAttribute(name,value){this[name]=value;}
  scrollIntoView(){}
  append(...children){this.children=(this.children||[]).concat(children);}
  remove(){this.removed=true;}
  querySelector(){return this.submitButton||(this.submitButton={disabled:false});} replaceChildren(...children){this.children=children;} reset(){} close(){} showModal(){this.open=true;} click(){return this.listeners.click?.();}
}
class NodeControl {constructor(){this.value='';this.children=[];this.listeners={};}addEventListener(name,fn){this.listeners[name]=fn;}replaceChildren(){this.children=[];this.value='';}append(child){this.children.push(child);if(this.children.length===1)this.value=child.value;} }
const node=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
let status={paired:true,online:false,connection_state:'connector_offline',can_configure:true,companies:[],installer_url:'/api/v1/integrations/tally/helper/download'};
const document={hidden:false,body:new Node(),getElementById:node,addEventListener(){},createElement:()=>new Node()};
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
  const fetchBeforeDownload=window.fetchWithAuth;
  let finishHead,downloadChecks=0;
  window.fetchWithAuth=async(url,options)=>{
    assert.equal(url,'/api/v1/integrations/tally/helper/download');assert.equal(options.method,'HEAD');downloadChecks++;
    return await new Promise(resolve=>finishHead=resolve);
  };
  const downloading=node('tallyDownload').listeners.click();
  await node('tallyDownload').listeners.click();
  assert.equal(downloadChecks,1,'repeated clicks must not start parallel installer requests');
  assert.equal(node('tallyDownload').disabled,true);
  assert.match(node('tallyReadStatus').textContent,/download check/);
  finishHead({ok:true});await downloading;
  const downloadLink=document.body.children.at(-1);
  assert.equal(downloadLink.href,status.installer_url,'browser streams authenticated same-origin URL directly');
  assert.equal(downloadLink.download,'PhilixaTallyConnectorSetup.exe');assert.equal(downloadLink.removed,true);
  assert.equal(node('tallyDownload').disabled,false);assert.match(node('tallyReadStatus').textContent,/Download requested/);
  const linksBefore=document.body.children.length;
  window.fetchWithAuth=async()=>({ok:false,status:403});await node('tallyDownload').listeners.click();
  assert.equal(document.body.children.length,linksBefore,'forbidden access must not launch download');
  assert.match(node('tallyReadStatus').textContent,/owner\/admin/);
  window.fetchWithAuth=fetchBeforeDownload;
  status={...status,distribution:{channel:'store',url:'https://apps.microsoft.com/detail/9ABCDEFGHIJK'},
    diagnostics:{package_kind:'msix',startup_configured:false,startup_state:'disabled_by_user'}};
  await intervals[0]();await flush();
  assert.match(node('tallyDownload').textContent,/Microsoft Store/);
  assert.match(node('tallyReadStatus').textContent,/Windows Startup Apps/);
  await node('tallyDownload').listeners.click();
  assert.equal(document.body.children.at(-1).href,status.distribution.url);
  assert.match(node('tallyReadStatus').textContent,/Microsoft Store opened/);
  assert(!node('tallyReadStatus').textContent.includes('Setup.exe'));
  status={...status,distribution:{channel:'unavailable',url:null},diagnostics:null};
  await intervals[0]();await flush();
  assert.equal(node('tallyDownload').dataset.channel,'legacy');
  status={...status,companies:[{name:'Remote Practice'}]};
  const beforeSetup=window.fetchWithAuth;
  window.fetchWithAuth=async(url,opts)=>{
    if(url.endsWith('/test'))return {ok:true,json:async()=>JSON.parse(opts.body).company?{non_gst:true,godowns:['Main Location'],purchase_ledgers:['Purchase','Purchase Return'],sales_ledgers:['Sales']}:{companies:['Remote Practice']}};
    return beforeSetup(url,opts);
  };
  await window.openBusinessPurchaseSetup('Remote Practice');
  assert.equal(node('tallyAdvanced').open,true,'guided setup exposes the existing mappings form');
  assert.equal(node('tallyConnectionForm').elements.company.value,'Remote Practice');
  assert.equal(node('tallyConnectionForm').elements.test_company.checked,false,'must not silently authorise a company as a test company');
  assert.equal(node('tallyConnectionForm').elements.purchase_ledger.value,'','multiple purchase ledgers require explicit selection');
  assert.equal(node('tallyPurchaseSetup').hidden,false);
  node('tallyAdvanced').open=false;
  window.fetchWithAuth=async()=>{throw new Error('Network unavailable');};
  const failedSetup=window.openBusinessPurchaseSetup();
  assert.equal(node('tallyAdvanced').open,true,'expand before waiting for network');
  assert.equal(node('tallyPurchaseSetup').disabled,true,'show busy state immediately');
  await failedSetup;
  assert.match(node('tallyReadStatus').textContent,/Purchase setup nahi khul saka: Network unavailable/,'configuration failure must be visible outside collapsed details');
  assert.equal(node('tallyPurchaseSetup').disabled,false);
  window.fetchWithAuth=async(url,opts)=>{
    if(url.endsWith('/test'))return {ok:true,json:async()=>JSON.parse(opts.body).company?{non_gst:true,godowns:['Main Location'],purchase_ledgers:['Purchase','Purchase Return'],sales_ledgers:['Sales']}:{companies:['Remote Practice']}};
    return beforeSetup(url,opts);
  };
  await window.openBusinessPurchaseSetup('Unapproved Company');
  assert.match(node('tallyConnectionStatus').textContent,/Company access badal/);
  let guidedClick;
  window.renderBusinessTally(new Node(),{purchase_setup:{company:'Remote Practice'},connect_tally:true},{submit(){},connect(){throw new Error('must not ask to pair again');},toolButton(parent,label,fn){assert.equal(label,'Purchase entry setup');guidedClick=fn;}});
  assert.equal(typeof guidedClick,'function');
  let gstClick,openedGST;
  window.openDraftWithDoc=async id=>{openedGST=id;};
  window.renderBusinessTally(new Node(),{gst_purchase_draft:{id:'gst-working-copy'}},{submit(){},connect(){throw new Error('must not re-pair GST');},toolButton(parent,label,fn){assert.equal(label,'GST purchase review');gstClick=fn;}});
  await gstClick();assert.equal(openedGST,'gst-working-copy','chat GST opens the existing validated Bills form');
  window.fetchWithAuth=beforeSetup;
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
  const proposalTools=new Node(),proposalButtons=[];
  const proposalData={draft_id:'draft-test',evidence_version:'evidence-test',purchase_assistant:{draft_id:'draft-test',revision:4,choices:[]},
    proposal:{company:'Test company',content:{party_name:'Supplier',lines:[{item_name:'Cement',quantity:'50',unit:'bags',rate:null}]},totals:{},provenance:{},can_prepare_preview:false},
    suggestions:[{field:'0:rate',value:'350',entry_date:'2026-10-02'}],issues:[],purchase_context:{status:'error',reason:'Connector update required'}};
  let proposalSubmission;
  window.renderBusinessTally(proposalTools,proposalData,{...callbacks,submit(...args){proposalSubmission=args;},toolButton(panel,label,fn){proposalButtons.push({label,fn});}});
  const proposalText=n=>[n.textContent||'',...(n.children||[]).map(proposalText)].join(' ');
  assert.match(proposalText(proposalTools),/Suggested ₹350/);
  assert.match(proposalText(proposalTools),/Connector update required/);
  assert(!proposalButtons.some(b=>b.label==='Validate & show final preview'),'incomplete proposals cannot offer confirmation');
  proposalButtons.find(b=>b.label==='Suggested rates sahi hain').fn();
  assert.equal(proposalSubmission[2].purchase_reply.evidence_version,'evidence-test');
  assert.equal(proposalSubmission[2].purchase_reply.accept_suggestions,true);
  const singleTools=new Node(),singleButtons=[];
  const singleData={...proposalData,task_id:'a'.repeat(32),status:'needs_input',
    purchase_assistant:{draft_id:'draft-test',revision:4,field:'party_name',choices:['Supplier']},
    purchase_context:{status:'ready',native_history_status:'ready'},suggestions:[]};
  window.renderBusinessTally(singleTools,singleData,{...callbacks,toolButton(panel,label,fn){singleButtons.push({panel,label,fn});}});
  assert.equal(singleTools.children.length,1,'one task panel contains summary and all controls');
  assert.equal(singleTools.children[0].className,'purchase-task-panel');
  assert(singleTools.children[0].children.some(n=>n.className==='purchase-inline-reply'),'grouped answer stays within the task card');
  assert(!singleButtons.some(b=>/Status dekhein|Check context status|Refresh Tally context/.test(b.label)),'no manual status steps in the task card');
  const grouped=new Node();let combined;
  window.renderBusinessTally(grouped,{task_id:'grouped-task',status:'needs_input',draft_id:'draft',
    proposal:{company:'Practice',totals:{total:'1750'},content:{party_name:'Sharma Traders',lines:[{item_name:'Cement',quantity:'5',unit:'bags',rate:'350'}]}},
    purchase_assistant:{field:'message'},situation_choices:['Bill mil gaya','Bill baad mein']},
    {...buttonCallbacks,submit(message){combined=message;}});
  const walk=n=>n&&typeof n==='object'?[n,...(n.children||[]).flatMap(walk)]:[];
  const form=walk(grouped).find(n=>n.className==='purchase-inline-reply');
  const selections=form.children.filter(n=>n.children?.some(c=>c.children?.some(o=>o.textContent==='Chunein…'))).map(n=>n.children[0]);
  assert.equal(selections.length,3,'bill, delivery and tax basis appear together');
  assert(selections.every(n=>n.value===''),'no transaction facts preselected');
  selections[0].value='Bill baad mein';selections[1].value='Maal aa gaya';selections[2].value='GST alag lagega';
  const date=walk(form).find(n=>n.type==='date');assert(!date.value,'received date must never default to today');date.value='2026-10-02';
  form.listeners.submit({preventDefault(){}});
  assert.match(combined,/Bill baad mein\. Maal aa gaya\. Received date: 2026-10-02\. GST alag lagega/,'one submit carries all selected facts');
  assert(!walk(form).some(n=>n.type==='number'),'known rate is not asked again');
  console.log('PASS: setup, status, reports, compact proposal, grouped facts and evidence-bound acceptance');
})().catch(error=>{console.error(error);process.exitCode=1;});


