const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.value='';this.files=[];this.listeners={};}
 append(...nodes){this.children.push(...nodes);if(this.tagName==='SELECT'&&!this.value&&nodes.length===1)this.value=nodes[0].value;}
 prepend(node){this.children.unshift(node);}replaceChildren(){this.children=[];this.value='';}
 get options(){return this.children;}setAttribute(k,v){this[k]=v;}addEventListener(k,fn){this.listeners[k]=fn;}click(){this.clicked=true;return this.onclick?.();}showModal(){this.open=true;}close(){this.open=false;this.listeners.close?.();}remove(){this.removed=true;}
}
const calls=[],urls=new Set(),host=new Element();let changes=0,fail=false,delayOriginal=false,releaseOriginal=null;const body=new Element();
const window={crypto:{randomUUID:()=> 'same-request-id-1234'},fetchWithAuth:async(path,options={})=>{
 calls.push({path,options});
 if(path.endsWith('/original')){const response={ok:true,blob:async()=>({type:'image/png'})};if(delayOriginal)return await new Promise(resolve=>{releaseOriginal=()=>resolve(response);});return response;}
 if(path.endsWith('/companies'))return {ok:true,json:async()=>({companies:[{id:'company',name:'Pilot'}]})};
 if(path.endsWith('/document-batches'))return {ok:true,json:async()=>({id:'batch'})};
 if(fail){fail=false;return {ok:false,json:async()=>({detail:'Upload interrupted'})};}
 return {ok:true,json:async()=>({document:{id:'document'}})};
}};
vm.runInNewContext(fs.readFileSync('app/web/business-chat-attachments.js','utf8'),{window,document:{createElement:t=>new Element(t),body},URL:{createObjectURL:()=>{urls.add('blob:test');return 'blob:test';},revokeObjectURL:u=>urls.delete(u)},FormData:class{append(){}}});
(async()=>{
 const controller=window.createChatAttachments(host,()=>changes++);controller.setEnabled(true);
 await controller.pick('scope');const box=host.children[0],picker=box.children[3],company=box.children[0].children[0];
 assert(picker.clicked);assert.equal(company.value,'company');
 picker.files=[{name:'dummy.png',size:200,type:'image/png',lastModified:1}];picker.onchange();assert(controller.hasFiles);assert.equal(urls.size,1);
 fail=true;await assert.rejects(()=>controller.stage('check bill','scope'),/interrupted/);
 const first=await controller.stage('check bill','scope');const second=await controller.stage('check bill','scope');
 assert.deepEqual(first,second);assert.equal(calls.filter(c=>c.path.endsWith('/documents')).length,2,'Retry only missing upload');
 assert.equal(calls.filter(c=>c.path.endsWith('/document-batches')).length,1,'Reuse staged batch');
 await assert.rejects(()=>controller.stage('changed','scope'),/uncertain/);
 await assert.rejects(()=>controller.stage('check bill','other'),/Workspace changed/);
 controller.clear();assert(!controller.hasFiles);assert.equal(urls.size,0);
 const cards=new Element();window.renderChatBillSources(cards,{attachment_sources:[{document_id:'doc',filename:'<script>bad</script>',drafts:[]}]});
 assert.equal(cards.children[0].children[0].textContent,'<script>bad</script>');
 const original=cards.children[0].children[1];await original.click();assert.equal(urls.size,1);assert(body.children.at(-1).open);
 window.closeChatBillPreviews();assert.equal(urls.size,0);assert(body.children.at(-1).removed);
 delayOriginal=true;const pending=original.click();window.closeChatBillPreviews();releaseOriginal();await pending;
 assert.equal(urls.size,0,'A response arriving after sign-out cannot open a private preview');
 picker.files=Array.from({length:51},(_,i)=>({name:i+'.pdf',size:10,type:'application/pdf'}));picker.onchange();assert(!controller.hasFiles);
 console.log('PASS: picker, file chips, private staging, failed upload retry, stable request, scope guard and blob cleanup');
})().catch(e=>{console.error(e);process.exitCode=1;});
