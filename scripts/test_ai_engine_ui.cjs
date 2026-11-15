const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('app/web/business-chat.js','utf8');
const controller=source.slice(source.indexOf('// AI Engine Switcher'),source.indexOf('  const taskPolls='));
function element(){return {disabled:false,classes:new Set(),classList:{add(v){this.owner.classes.add(v)},remove(v){this.owner.classes.delete(v)}},addEventListener(k,f){this[k]=f}}}
const groq=element(),gemini=element();for(const el of [groq,gemini])el.classList.owner=el;
let selected='groq',fail=false,release;const requests=[];
const window={addEventListener(){},fetchWithAuth:async(path,options)=>{
 requests.push({path,options});
 if(options?.method==='POST'){
  await new Promise(r=>release=r);
  if(fail)return {ok:false};
  selected=JSON.parse(options.body).engine;
 }
 return {ok:true,json:async()=>({engine:selected})};
}};
vm.runInNewContext(controller,{window,document:{getElementById:id=>id==='engineGroqBtn'?groq:gemini},console});
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 await tick();assert(groq.classes.has('active'));
 const first=gemini.click();assert(groq.disabled&&gemini.disabled);assert(!gemini.classes.has('active'));
 release();await first;assert(gemini.classes.has('active'));assert(!groq.disabled&&!gemini.disabled);
 fail=true;const second=groq.click();release();await second;
 assert(gemini.classes.has('active'));assert(!groq.classes.has('active'));
 assert.equal(requests.filter(r=>r.options?.method==='POST').length,2);
 console.log('PASS: provider switch waits for server acknowledgement; failed save retains prior provider; controls re-enable');
})().catch(e=>{console.error(e);process.exit(1)});
