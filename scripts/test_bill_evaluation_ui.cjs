const assert=require('assert'),h=require('./test_purchase_drafts_ui.cjs');
(async()=>{
 h.reset();let samples=0;
 class Meter{constructor(options){this.options=options;}select(context){this.context=context;}activity(){}async flush(){if(this.context)await this.options.send({context:this.context,body:{event_id:'a'.repeat(32),revision:0,active_ms:1000}});}}
 const row={id:'draft',company_id:'company',revision:0,status:'draft',editable:true,content:{party_name:'Supplier',invoice_number:'EVAL',entry_date:'2026-10-02',lines:[{item_name:'Cement',quantity:'2',unit:'bags',rate:'100'}]}};
 const p=h.page({reviewMeter:Meter,respond:async(url,options)=>{
  if(url.endsWith('/review-time')){assert.equal(options.method,'POST','review samples must POST, never GET with body');samples++;return {recorded:true};}
  if(url.endsWith('/evaluation-metrics'))return {correction_count:2,active_review_ms:1000,processing_latency_ms:null,provider_cost_usd:null};
  if(url.includes('/review-queue?'))return {bills:[{...row,kind:'draft',queue_bucket:'needs_attention'}],counts:{needs_attention:1},total:1};
  if(url.endsWith('/draft'))return row;if(url.endsWith('/audit'))return {events:[]};
 }});
 await p.get('businessDraftsBtn').click();await h.flush();await p.get('billDraftList').children[0].click();await h.flush();
 await p.get('billEvaluationMetrics').click();await h.flush();assert.equal(samples,1);
 assert.match(p.get('billDraftStatus').textContent,/Corrections: 2 fields/);assert.match(p.get('billDraftStatus').textContent,/Provider cost: unknown/);
 assert.match(p.get('billDraftStatus').textContent,/Real-world accuracy unverified/);
 console.log('PASS: real Bills controller posts review samples and keeps missing processing/cost unknown');
})().catch(e=>{console.error(e);process.exitCode=1;});
