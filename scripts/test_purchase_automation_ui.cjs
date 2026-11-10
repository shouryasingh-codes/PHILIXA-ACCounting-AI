const assert=require('assert'),h=require('./test_purchase_drafts_ui.cjs');
(async()=>{
 h.reset();let policy={mode:'shadow',suppliers:['Supplier'],items:['Cement'],per_invoice:'500',daily_amount:'1000',daily_count:2},revision=1;
 const calls=[];
 const row={id:'draft',company_id:'company',revision:0,status:'draft',editable:true,content:{party_name:'Supplier',invoice_number:'UI-D8',entry_date:'2026-10-02',lines:[{item_name:'Cement',unit:'bags',quantity:'2',rate:'100'}]}};
 const decision={decision:'auto_post',revision:1,policy_revision:1,reasons:['Shadow mode: human approval required.']};
 const p=h.page({respond:async(url,options)=>{
   calls.push({url,options});
   if(url.endsWith('/automation/pause')){policy.mode='paused';return {revision:++revision};}
   if(url.endsWith('/automation')){
     if(options.method==='PUT'){const body=JSON.parse(options.body);assert.equal(body.revision,revision);policy=body;revision++;}
     return {revision,policy,enabled:true,usage:{count:0,amount:'0'}};
   }
   if(url.endsWith('/automation-decisions'))return {decisions:[]};
   if(url.endsWith('/automation-evaluate')){row.revision++;return decision;}
   if(url.includes('/review-queue?'))return {bills:[{...row,kind:'draft',queue_bucket:'needs_attention',ready:false}],counts:{needs_attention:1},total:1};
   if(url.endsWith('/draft'))return row;
   if(url.endsWith('/audit'))return {events:[]};
 }});
 await p.get('businessDraftsBtn').click();await h.flush();await p.get('billDraftList').children[0].click();await h.flush();
 assert.equal(p.get('billAutomationSave').disabled,true);
 await p.get('billAutomationLoad').click();await h.flush();assert.equal(p.get('billAutomationMode').value,'shadow');assert.equal(p.get('billAutomationSave').disabled,false);
 p.get('billAutomationInvoice').value='250';await p.get('billAutomationSave').click();await h.flush();assert.equal(policy.per_invoice,'250');assert.deepEqual(policy.suppliers,['Supplier']);
 p.get('billDraftForm').dataset.dirty='true';await p.get('billAutomationEvaluate').click();assert.match(p.get('billAutomationStatus').textContent,/Save bill changes/);
 assert.equal(calls.filter(c=>c.url.endsWith('/automation-evaluate')).length,0);
 p.get('billDraftForm').dataset.dirty='false';await p.get('billAutomationEvaluate').click();await h.flush();
 assert.match(p.get('billAutomationDecisions').children[0].textContent,/human approval/);
 assert.equal(calls.filter(c=>c.url.endsWith('/confirm')).length,0,'UI never synthesizes a human approval');
 await p.get('billAutomationPause').click();await h.flush();assert.equal(p.get('billAutomationMode').value,'paused');assert.equal(p.get('billAutomationSave').disabled,true);
 console.log('PASS: scoped policy load/save, limits, dirty draft block, shadow decisions, explicit pause and no implicit human approval');
})().catch(e=>{console.error(e);process.exitCode=1;});
