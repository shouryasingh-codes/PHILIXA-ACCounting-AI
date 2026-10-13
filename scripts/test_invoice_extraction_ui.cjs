// Exercise Day 4 Side-by-side OCR draft view and extraction review controller.
const fs=require('fs'),vm=require('vm'),assert=require('assert');

class ClassList {
  constructor(){this.classes=new Set();}
  add(c){this.classes.add(c);}
  remove(c){this.classes.delete(c);}
  contains(c){return this.classes.has(c);}
}

class Element {
  constructor(tag='div'){
    this.tag=tag;this.children=[];this.listeners={};this.value='';this.disabled=false;
    this.hidden=false;this.open=false;this._textContent='';this.classList=new ClassList();
  }
  get textContent(){
    if(this._textContent)return this._textContent;
    return this.children.map(c=>typeof c==='string'?c:(c.textContent||'')).join(' ');
  }
  set textContent(v){this._textContent=v;}
  append(...values){this.children.push(...values);}
  replaceChildren(...values){this.children=[...values];this._textContent='';}
  setAttribute(key,value){this[key]=value;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  showModal(){this.open=true;}
  close(){this.open=false;this.listeners.close?.();}
}

let scope={user_id:'owner',organization_id:'workspace',session_id:'session'};
let record=null, requests=[];

function makePage(){
  const nodes=new Map();
  const get=id=>{
    if(!nodes.has(id))nodes.set(id,new Element());
    return nodes.get(id);
  };

  const keys=['party_name','entry_date','godown','invoice_number'];
  const form=get('billDraftForm');
  const inputs=Object.fromEntries(keys.map(k=>[k,new Element('input')]));
  form.elements={namedItem:k=>inputs[k]};
  form.reset=()=>{for(const inp of Object.values(inputs))inp.value='';};
  form.querySelectorAll=()=>[get('billDraftSave'),get('billDraftMakePreview')];

  const window={
    getBusinessChatScope:()=>scope,
    fetchWithAuth:async(url,options={})=>{
      requests.push({url,options});
      let data={};let ok=true;
      if(url.endsWith('/companies')){
        data={companies:[{id:'comp-1',name:'UltraTech Pilot'}]};
      }else if(url.includes('/masters')){
        data={items:[{name:'Cement',unit:'bags'}],suppliers:['UltraTech Cement Ltd']};
      }else if(url.endsWith('/purchase-drafts')&&(!options.method||options.method==='GET')){
        data={drafts:record?[JSON.parse(JSON.stringify(record))]:[]};
      }else if(url.includes('/audit')){
        data={events:[{revision:0,kind:'created_from_extraction',created_at:new Date().toISOString()}]};
      }else if(url.includes('/purchase-drafts/draft-split-1')){
        data={...JSON.parse(JSON.stringify(record)), id:'draft-split-1', content:{...record.content, invoice_number:'INV-1'}};
      }else if(url.includes('/purchase-drafts/draft-1')){
        data=JSON.parse(JSON.stringify(record));
      }else if(url.includes('/documents/doc-1/pages/1')){
        return {ok:true,blob:async()=>({type:'image/png'})};
      }else if(url.includes('/documents/doc-1/pages/2')){
        return {ok:true,blob:async()=>({type:'image/png'})};
      }else if(url.includes('/documents/doc-1/original')){
        return {ok:true,blob:async()=>({type:'application/pdf'})};
      }else if(url.includes('/documents/doc-1/split')){
        const splitDrafts=[
          {...JSON.parse(JSON.stringify(record)), id:'draft-split-1', content:{...record.content, invoice_number:'INV-1'}},
          {...JSON.parse(JSON.stringify(record)), id:'draft-split-2', content:{...record.content, invoice_number:'INV-2'}}
        ];
        data={split:true, drafts:splitDrafts};
      }else if(url.includes('/documents/doc-1')){
        data={id:'doc-1',filename:'invoice.pdf',page_count:2,media_type:'application/pdf',status:'ready'};
      }
      return {ok,json:async()=>data,blob:async()=>({type:'image/png'})};
    }
  };

  const document={
    getElementById:get,
    createElement:tag=>new Element(tag)
  };

  global.URL={createObjectURL:()=>'blob://synthetic-page',revokeObjectURL:()=>{}};

  vm.runInNewContext(fs.readFileSync('app/web/business-drafts.js','utf8'),{window,document,JSON,Date,console,URL:global.URL});
  return {get,inputs,window};
}

const flush=async()=>{for(let i=0;i<80;i++)await Promise.resolve();};

(async()=>{
  console.log('Testing Day 4 side-by-side OCR UI controller…');

  // Seed an extracted record linked to doc-1
  record={
    id:'draft-1',
    company_id:'comp-1',
    document_id:'doc-1',
    document_filename:'invoice.pdf',
    revision:0,
    status:'needs_review',
    editable:true,
    content:{
      party_name:'UltraTech Cement Ltd',
      invoice_number:'INV-2026-001',
      entry_date:'2026-10-10',
      godown:'Main Godown',
      lines:[
        {item_name:'Cement',quantity:'10',unit:'bags',rate:'350.00'}
      ]
    },
    extraction_metadata:{
      status:'needs_review',
      confidence:{overall:0.95, supplier_name:0.98, lines:0.92},
      source_pages:[1,2],
      multiple_invoices_detected:true,
      warnings:[
        'Supplier matched to Sundry Creditor: UltraTech Cement Ltd',
        'Multiple invoices detected in document (2 invoices found). Splitting required.'
      ],
      line_evidence:[
        {line_index:0, unclear:false, warnings:[]}
      ]
    }
  };

  const p=makePage();
  p.get('businessDraftsBtn').listeners.click();
  await flush();

  // Open the extracted draft
  assert.equal(p.get('billDraftList').children.length, 1);
  await p.get('billDraftList').children[0].listeners.click();
  await flush();

  // 1. Verify side-by-side layout was activated
  assert.equal(p.get('businessDrafts').classList.contains('side-by-side'), true, 'Dialog has side-by-side class');
  assert.equal(p.get('billDraftsLayout').classList.contains('has-doc'), true, 'Layout has has-doc class');
  assert.equal(p.get('billDraftDocPanel').hidden, false, 'Document viewer panel is visible');

  // 2. Verify document page loaded
  assert.match(p.get('billDraftDocPage').textContent, /Page 1 \/ 2/);
  assert.equal(p.get('billDraftDocPrev').disabled, true, 'Page 1 previous is disabled');
  assert.equal(p.get('billDraftDocNext').disabled, false, 'Page 1 next is enabled');

  // Navigate to Page 2
  await p.get('billDraftDocNext').listeners.click();
  await flush();
  assert.match(p.get('billDraftDocPage').textContent, /Page 2 \/ 2/);
  assert.equal(p.get('billDraftDocPrev').disabled, false, 'Page 2 previous is enabled');

  // 3. Verify Extraction Review Banner
  const banner=p.get('billDraftExtractionReview');
  assert.equal(banner.hidden, false, 'Extraction review banner is visible');
  assert.match(banner.textContent, /95% model confidence/);
  assert.match(banner.textContent, /Review required/);
  assert.match(banner.textContent, /Multiple invoices detected/);

  // 4. Verify Split Button presence and action
  const splitBtn=banner.children.find(c=>c.textContent?.includes('Split into separate'));
  assert.ok(splitBtn, 'Split invoices button exists');
  await splitBtn.listeners.click();
  await flush();
  assert.match(p.get('billDraftStatus').textContent, /split into 2 drafts/);

  // 5. Verify fields populated from the split draft
  assert.equal(p.inputs.party_name.value, 'UltraTech Cement Ltd');
  assert.equal(p.inputs.invoice_number.value, 'INV-1');
  assert.equal(p.inputs.entry_date.value, '2026-10-10');

  // 6. Test window.openDraftWithDoc
  p.get('businessDrafts').close();
  assert.equal(p.get('businessDrafts').open, false);
  await p.window.openDraftWithDoc('draft-1');
  await flush();
  assert.equal(p.get('businessDrafts').open, true);
  assert.equal(p.inputs.party_name.value, 'UltraTech Cement Ltd');
  assert.equal(p.inputs.invoice_number.value, 'INV-2026-001');
  assert.equal(p.get('billDraftDocPanel').hidden, false);

  console.log('✓ Day 4 side-by-side OCR UI tests passed successfully.');
})();
