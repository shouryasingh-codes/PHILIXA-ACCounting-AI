// Exercise the real Bills controller with a scoped fake API. No Tally/network calls.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let scope={user_id:'owner',organization_id:'workspace',session_id:'session'},record=null,events=[],requests=[];
const keys=['party_name','item_name','quantity','unit','rate','entry_date','godown','invoice_number','tax_treatment','supplier_gstin','place_of_supply','invoice_discount','round_off','invoice_total'];
class ClassList {
  constructor(){this.classes=new Set();}
  add(c){this.classes.add(c);}
  remove(c){this.classes.delete(c);}
  contains(c){return this.classes.has(c);}
}
class Element {
  constructor(){this.children=[];this.listeners={};this.value='';this.disabled=false;this.hidden=false;this.open=false;this.textContent='';this.classList=new ClassList();}
  append(...values){this.children.push(...values);}
  replaceChildren(...values){this.children=[...values];}
  setAttribute(key,value){this[key]=value;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  showModal(){this.open=true;}
  close(){this.open=false;this.listeners.close?.();}
}
function page(){
  const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const document={getElementById:get,createElement:()=>new Element()};
  const form=get('billDraftForm');const inputs=Object.fromEntries(keys.map(key=>[key,new Element()]));
  form.elements={namedItem:key=>inputs[key]};form.reset=()=>{for(const input of Object.values(inputs))input.value='';};
  form.querySelectorAll=()=>[get('billDraftSave'),get('billDraftMakePreview')];
  const window={getBusinessChatScope:()=>scope,fetchWithAuth:async(url,options={})=>{
    requests.push({url,options});let data;let ok=true;const body=options.body?JSON.parse(options.body):null;
    const snapshot=()=>JSON.parse(JSON.stringify(record));
    if(url.endsWith('/companies'))data={companies:[{id:'company',name:'Pilot Test'}]};
    else if(url.endsWith('/masters'))data={items:[{name:'Cement',unit:'bags'},{name:'Bricks',unit:'pcs'}],suppliers:['Supplier']};
    else if(url.endsWith('/tax-profile'))data={revision:options.method==='PUT'?1:0,profile:{ledgers:{CGST:'Input CGST',SGST:'Input SGST'},rounding_ledger:'Round Off'},candidates:{CGST:['Input CGST'],SGST:['Input SGST'],IGST:['Input IGST'],UTGST:[]},rounding_candidates:['Round Off']};
    else if(url.endsWith('/tax-check'))data={taxable_total:'1000.00',tax_ledgers:[{head:'CGST',amount:'90.00'},{head:'SGST',amount:'90.00'}],round_off:'0.00',total:'1180.00'};
    else if(url.endsWith('/audit'))data={events};
    else if(url.endsWith('/preview')){
      assert.equal(body.revision,record.revision);record.status='preview';record.action_id='token';record.revision++;
      events.push({revision:record.revision,kind:'preview_created',created_at:new Date().toISOString()});
      data={response:'Preview only',preview:{token:'token',can_confirm:!record.content.tax_treatment,blockers:record.content.tax_treatment?['GST live acceptance pending']:[],lines:['8 bags × ₹350 = ₹2800']}};
    }else if(url.endsWith('/confirm')){assert.deepEqual(body,{token:'token',approve:true});record.status='queued';record.editable=false;data={response:'Sync pending'};}
    else if(url.endsWith('/purchase-drafts')&&options.method==='POST'){
      record={id:'draft',company_id:body.company_id,content:body.content,revision:0,status:'draft',editable:true};
      events=[{revision:0,kind:'created',created_at:new Date().toISOString()}];data=snapshot();
    }else if(url.endsWith('/purchase-drafts'))data={drafts:record?[snapshot()]:[]};
    else if(options.method==='PUT'){
      if(body.revision!==record.revision){ok=false;data={detail:'Stale revision'};}
      else{record.content=body.content;record.revision++;events.push({revision:record.revision,kind:'edited',created_at:new Date().toISOString()});data=snapshot();}
    }else data=snapshot();
    return {ok,json:async()=>JSON.parse(JSON.stringify(data))};
  }};
  const URL={createObjectURL:()=>'blob://mock',revokeObjectURL:()=>{}};
  vm.runInNewContext(fs.readFileSync('app/web/business-drafts.js','utf8'),{window,document,JSON,Date,console,URL});
  const line=index=>Object.fromEntries(['item_name','quantity','unit','rate'].map((key,i)=>[key,get('billDraftLines').children[index].children[i+1].children[0]]));
  return {get,inputs,line};
}
const flush=async()=>{for(let i=0;i<80;i++)await Promise.resolve();};
if(require.main===module)(async()=>{
  let p=page();p.get('businessDraftsBtn').listeners.click();await flush();
  p.get('billDraftCompany').value='company';p.inputs.party_name.value='Supplier';
  await p.get('billDraftForm').listeners.submit({preventDefault(){}});await flush();
  assert.equal(record.revision,0);assert.equal(record.action_id,undefined);
  assert.equal(p.get('billDraftList').children.length,1);
  p.get('businessDrafts').close();p=page();p.get('businessDraftsBtn').listeners.click();await flush();
  await p.get('billDraftList').children[0].listeners.click();await flush();
  assert.equal(p.inputs.party_name.value,'Supplier','reopen uses persisted API draft');
  Object.assign(p.line(0).item_name,{value:'Cement'});p.line(0).item_name.listeners.change();assert.equal(p.line(0).unit.value,'bags');p.line(0).quantity.value='8';p.line(0).rate.value='350';p.inputs.entry_date.value='2026-10-01';
  p.get('billDraftAddLine').listeners.click();
  p.line(1).item_name.value='Bricks';p.line(1).quantity.value='2';p.line(1).unit.value='pcs';p.line(1).rate.value='400';
  p.line(1).rate.listeners.input();assert.equal(p.get('billDraftTotal').textContent,'Total: ₹3600.00 (non-GST)');
  await p.get('billDraftMakePreview').listeners.click();
  assert.match(p.get('billDraftStatus').textContent,/Pehle edited/);
  await p.get('billDraftForm').listeners.submit({preventDefault(){}});await flush();
  assert.equal(record.revision,1);assert.equal(p.get('billDraftAudit').children.length,2);
  assert.equal(record.content.lines.length,2,'all lines persist in the draft');
  await p.get('billDraftMakePreview').listeners.click();await flush();
  assert.equal(record.status,'preview');assert.equal(p.get('billDraftAudit').children.length,3);
  assert.equal(requests.filter(r=>r.url.endsWith('/confirm')).length,0,'creating/reloading a preview never approves');
  const confirm=p.get('billDraftPreview').children.at(-1);await confirm.listeners.click();await flush();
  assert.equal(record.status,'queued');assert.equal(requests.filter(r=>r.url.endsWith('/confirm')).length,1);
  assert.equal(p.line(0).quantity.disabled,true);assert.equal(p.line(1).rate.disabled,true);assert.equal(p.get('billDraftSave').hidden,true);
  scope={...scope,organization_id:'other'};await confirm.listeners.click();
  assert.equal(requests.filter(r=>r.url.endsWith('/confirm')).length,1,'stale workspace cannot confirm');
  p.get('workspaceSelect').listeners.change();assert.equal(p.get('businessDrafts').open,false);
  assert.equal(p.get('billDraftList').children.length,0,'scope switch clears draft UI');
  console.log('PASS: durable reopen, revision history, save-before-preview, explicit approval, pending edit lock and workspace clearing');
})().catch(error=>{console.error(error);process.exitCode=1;});

module.exports={page,flush,reset:()=>{record=null;events=[];requests=[];scope={user_id:'owner',organization_id:'workspace',session_id:'session'};},getRecord:()=>record,getRequests:()=>requests};
