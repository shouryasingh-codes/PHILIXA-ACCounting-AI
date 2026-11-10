const assert=require('assert'),Meter=require('../app/web/bill-review-meter.js');
(async()=>{
 let time=0,active=true,samples=[],fail=true,n=0;
 const meter=new Meter({clock:()=>time,id:()=>String(++n).padStart(32,'0'),active:()=>active,send:async s=>{if(fail)throw Error('offline');samples.push(s);}});
 meter.select({id:'A',scope:'workspace',revision:0});
 time=2500;meter.tick();time=5000;meter.tick();active=false;time=7500;meter.tick();active=true;time=20000;meter.tick();
 await assert.rejects(meter.flush());assert.equal(meter.pending[0].body.active_ms,5000);const token=meter.pending[0].body.event_id;
 fail=false;await meter.flush();assert.equal(samples.length,1);assert.equal(samples[0].body.event_id,token,'retry uses original idempotency token');
 meter.activity();time=22500;meter.tick();meter.select({id:'B',scope:'workspace',revision:1});await meter.flush();assert.equal(samples[1].context.id,'A','switch preserves bill attribution');
 time=50000;meter.tick();await meter.flush();assert.equal(samples.length,2,'idle/suspended gaps excluded');
 console.log('PASS: visible active intervals only, idle gaps excluded, retry idempotency and per-bill attribution');
})().catch(e=>{console.error(e);process.exitCode=1;});
