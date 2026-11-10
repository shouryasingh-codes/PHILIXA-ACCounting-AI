const assert=require('assert'),h=require('./test_purchase_drafts_ui.cjs');
(async()=>{
 h.reset();const requests=[];
 let row={id:'a'.repeat(32),company_id:'company',revision:0,editable:true,status:'needs_review',kind:'draft',queue_bucket:'needs_attention',ready:false,
 content:{party_name:'Supplier',entry_date:'2026-10-02',invoice_number:'D7',lines:[{item_name:'Cement',quantity:'2',unit:'bags',rate:'100'}]},
 extraction_metadata:{warnings:[],confidence:{},field_evidence:{party_name:{raw:'Supplier OCR'}},line_evidence:[{item_name:{raw:'Cement OCR'},warnings:[]}]}};
 const p=h.page({respond:async(url,options)=>{
  requests.push({url,options});
  if(url.includes('/review-queue?'))return {bills:[row],counts:{needs_attention:1},total:1};
  if(url.endsWith('/companies/company/aliases'))return {aliases:[{kind:'supplier',source:'Supplier OCR',target:'Supplier',valid:false}]};
  if(url.endsWith('/audit'))return {events:[]};
  if(url.endsWith('/aliases')){const b=JSON.parse(options.body);assert.equal(b.revision,row.revision);assert.ok(['supplier','item'].includes(b.kind));row.revision++;return row;}
  if(url.endsWith('/'+row.id)){if(options.method==='PUT'){row.content=JSON.parse(options.body).content;row.revision++;}return row;}
 }});
 await p.get('businessDraftsBtn').click();await h.flush();await p.get('billDraftList').children[0].click();await h.flush();
 assert.equal(requests.filter(r=>r.options.method==='POST').length,0,'opening a draft never learns a correction');
 await p.get('billRememberSupplier').click();await h.flush();
 assert.equal(JSON.parse(requests.find(r=>r.url.endsWith('/aliases')&&r.options.method==='POST').options.body).kind,'supplier');
 const button=p.get('billDraftLines').children[0].children.find(c=>c.textContent==='Remember item correction for this company');
 await button.click();await h.flush();
 const learned=requests.filter(r=>r.url.endsWith('/aliases')&&r.options.method==='POST');assert.equal(learned.length,2);
 assert.equal(JSON.parse(learned[1].options.body).line_index,0);
 await p.get('billCompanyMemory').click();await h.flush();assert.match(p.get('billDraftPreview').children[0].textContent,/Master changed/);
 assert.ok(!requests.some(r=>r.url.endsWith('/confirm')||r.url.endsWith('/bulk-approve')),'remembering never posts');
 console.log('PASS: aliases require explicit field actions, revision checked, changed master shown, no posting');
})().catch(e=>{console.error(e);process.exitCode=1;});
