const {chromium}=require('C:/Users/admin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1365,height:1000}});
  const failures=[];page.on('pageerror',e=>failures.push(e.message));
  const dir=path.resolve('output/stack-research-2026-10-28');
  await page.goto(pathToFileURL(path.join(dir,'philixa-stack-research.html')).href);
  for(const name of ['Overview','Competitors','Guidance','Sources and evidence limits']){
   if(await page.getByRole('heading',{name,exact:true}).count()!==1)throw Error('Missing section '+name);
  }
  const audit=await page.evaluate(()=>({title:document.title,links:document.querySelectorAll('a[href^="https://"]').length,
    overflow:document.documentElement.scrollWidth>innerWidth,
    nav:[...document.querySelectorAll('nav a')].every(a=>document.querySelector(a.getAttribute('href')))}));
  if(failures.length||audit.overflow||!audit.nav)throw Error(JSON.stringify({failures,audit}));
  await page.screenshot({path:path.join(dir,'research-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile page overflow');
  await page.screenshot({path:path.join(dir,'research-mobile.png')});
  console.log(JSON.stringify({status:'PASS',...audit,mobile:'390px: no page overflow'}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});
