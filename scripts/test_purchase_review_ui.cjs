const assert=require('assert'),h=require('./test_purchase_drafts_ui.cjs');
(async()=>{
 h.reset();
 const rows=[1,2,3].map((n)=>({id:String(n).padStart(32,'0'),kind:'draft',company_id:'company',
   action_id:String(n+10).padStart(32,'0'),revision:2,ready:n<3,queue_bucket:n<3?'ready':'needs_attention',
   status:n<3?'preview':'draft',editable:true,
   content:{party_name:'Supplier',invoice_number:'BILL-'+n,entry_date:'2026-10-01',lines:[{item_name:'Cement',quantity:'8',unit:'bags',rate:'350'}]}}));
 const calls=[];
 const p=h.page({respond:async(url,options)=>{
   calls.push({url,options});
   if(url.includes('/review-queue?'))return {bills:rows,counts:{ready:2,needs_attention:1,processing:0,posting:0,verified:0},total:3};
   if(url.endsWith('/bulk-approve')){
     const items=JSON.parse(options.body).items;
     assert.equal(items.length,2);assert.equal(items[0].revision,2);assert.equal(items[0].action_id,rows[0].action_id);
     return {approved:1,failed:1,results:[{draft_id:rows[0].id,ok:true,response:'Queued'}, {draft_id:rows[1].id,ok:false,response:'Stale revision'}]};
   }
   if(url.endsWith('/audit'))return {events:[]};
   const row=rows.find(r=>url.endsWith('/'+r.id));
   if(row&&options.method==='PUT'){row.content=JSON.parse(options.body).content;row.revision++;row.action_id=null;return row;}
   if(row)return row;
   if(url.endsWith('/preview')){
     const row=rows[0];assert.equal(JSON.parse(options.body).revision,3);assert.equal(row.content.lines[0].quantity,'9');
     row.revision++;row.action_id='fresh';return {response:'Validated corrected values',preview:{can_confirm:true,token:'fresh',lines:['3150']}};
   }
 }});
 await p.get('businessDraftsBtn').listeners.click();await h.flush();
 assert.match(p.get('billQueueCounts').textContent,/ready: 2/);
 assert.equal(p.get('billQueueApprove').disabled,true);
 p.get('billQueueSelectReady').click();assert.equal(p.get('billQueueApprove').disabled,false);
 await p.get('billQueueApprove').click();await h.flush();
 assert.equal(p.get('billQueueResults').children.length,2);
 assert.match(p.get('billQueueResults').children[1].textContent,/Stale revision/);
 assert.equal(p.get('billQueueApprove').disabled,true);
 await p.get('billDraftList').children[0].click();await h.flush();
 p.line(0).quantity.value='9';await p.get('billQueueValidate').click();await h.flush();
 assert.ok(calls.some(c=>c.url.endsWith('/preview')),'save & validate reruns server validation');
 assert.equal(rows[0].revision,4);
 assert.equal(calls.filter(c=>c.url.endsWith('/bulk-approve')).length,1,'validation never approves');
 await p.get('billQueueView').listeners.change({target:{value:'posting'}});await h.flush();
 assert.ok(calls.some(c=>c.url.includes('view=posting')));
 console.log('PASS: selection carries revision/action, independent results, view filter, corrected values revalidate without approval');
})().catch(e=>{console.error(e);process.exitCode=1;});
