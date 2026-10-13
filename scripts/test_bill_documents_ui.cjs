// Real documents controller, scoped fake API. Verify reload, duplicates, polling and blob cleanup.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let scope={organization_id:'workspace',user_id:'owner',session_id:'session'},storedBatch=null,storedDoc=null;
const calls=[],urls=new Set();let openedDraft=null;
class Element{
  constructor(){this.children=[];this.listeners={};this.value='';this.files=[];this.dataset={};this.disabled=false;this.open=false;this.textContent='';}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
  addEventListener(event,fn){this.listeners[event]=fn;}
  showModal(){this.open=true;}
  close(){this.open=false;this.listeners.close?.();}
  click(){this.listeners.click?.();}
}
function page(){const nodes=new Map(),timers=new Map();let timer=0;
  const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
  const window={openDraftWithDoc:async id=>{openedDraft=id;},getBusinessChatScope:()=>scope,fetchWithAuth:async(path,options={})=>{
    calls.push(path);let data;
    if(path.endsWith('/purchase-drafts/companies'))data={companies:[{id:'company',name:'Pilot Test'}]};
    else if(path.endsWith('/document-batches')&&options.method==='POST'){
      assert.equal(JSON.parse(options.body).company_id,'company');storedBatch={id:'batch',company_id:'company',created_at:new Date().toISOString()};data=storedBatch;
    }else if(path.endsWith('/document-batches'))data={batches:storedBatch?[storedBatch]:[]};
    else if(path.endsWith('/documents')&&options.method==='POST'){
      const duplicate=Boolean(storedDoc);storedDoc=storedDoc||{id:'doc',filename:'bill.png',media_type:'image/png',status:'queued',page_count:null,message:'Uploaded · pending'};data={document:storedDoc,duplicate};
    }else if(path.endsWith('/document-batches/batch'))data={...storedBatch,documents:storedDoc?[storedDoc]:[]};
    else if(path.endsWith('/extract')){assert.equal(options.method,'POST');
      if(storedDoc.extraction_status==='needs_review')data={status:'needs_review',drafts:[{id:'extracted'}]};
      else {storedDoc.extraction_status='queued';data={status:'queued',drafts:[]};}
    }
    else if(path.endsWith('/original'))return {ok:true,blob:async()=>({bytes:'original'})};
    else throw new Error('Unexpected route '+path);
    return {ok:true,json:async()=>JSON.parse(JSON.stringify(data))};
  }};
  const context={window,document:{getElementById:get,createElement:()=>new Element()},console,Date,JSON,
    FormData:class{append(k,v){this[k]=v;}},MutationObserver:class{observe(){}},
    setTimeout:fn=>{const id=++timer;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
    URL:{createObjectURL:()=>{const url='blob:private'+urls.size;urls.add(url);return url;},revokeObjectURL:url=>urls.delete(url)}};
  vm.runInNewContext(fs.readFileSync('app/web/business-documents.js','utf8'),context);
  return {get,timers};
}
async function flush(){for(let i=0;i<100;i++)await Promise.resolve();}
(async()=>{
  let p=page();p.get('businessDocumentsBtn').click();await flush();p.get('documentCompany').value='company';
  p.get('documentFiles').files=[{name:'bill.png',size:100}];await p.get('documentUpload').listeners.click();await flush();
  assert.equal(storedDoc.status,'queued');assert.match(p.get('documentStatus').textContent,/1 new files/);
  assert.ok(p.timers.size,'pending status is polled');
  p.get('businessDocuments').close();p=page();p.get('businessDocumentsBtn').click();await flush();
  assert.equal(p.get('documentList').children.length,1,'reload restores server batch');
  storedDoc={...storedDoc,status:'ready',page_count:1,message:'File ready'};
  const poll=p.timers.values().next().value;await poll();await flush();
  const card=p.get('documentList').children[0];await card.children.find(c=>c.className==='doc-card-actions').children[0].listeners.click();await flush();
  assert.equal(p.get('documentViewer').children.length,1);assert.equal(urls.size,1);
  p.get('documentFiles').files=[{name:'renamed.png',size:100}];await p.get('documentUpload').listeners.click();await flush();
  assert.match(p.get('documentStatus').textContent,/1 already saved/);assert.equal(p.get('documentList').children.length,1);
  let actions=p.get('documentList').children[0].children.find(c=>c.className==='doc-card-actions');
  await actions.children[1].listeners.click();await flush();
  assert.equal(storedDoc.extraction_status,'queued');assert.match(p.get('documentStatus').textContent,/Extraction queued/);
  assert.ok(p.timers.size,'extraction processing is polled');
  p.get('businessDocuments').close();p=page();p.get('businessDocumentsBtn').click();await flush();
  storedDoc.extraction_status='needs_review';await p.timers.values().next().value();await flush();
  actions=p.get('documentList').children[0].children.find(c=>c.className==='doc-card-actions');
  assert.match(actions.children[1].textContent,/Review extracted/);
  await actions.children[1].listeners.click();await flush();assert.equal(openedDraft,'extracted');
  assert.equal(p.get('businessDocuments').open,false);
  p.get('businessDocumentsBtn').click();await flush();
  scope={...scope,organization_id:'other'};p.get('workspaceSelect').listeners.change();
  assert.equal(p.get('businessDocuments').open,false);assert.equal(urls.size,0);assert.equal(p.get('documentList').children.length,0);
  assert.ok(calls.every(path=>path.startsWith('/api/v1/business/')),'originals only use authenticated app URLs');
  console.log('PASS: sequential upload, durable reload, pending polling, duplicate reuse, private blob viewer and scope cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
