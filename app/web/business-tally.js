// Local Tally pilot. All actions use authenticated backend APIs; never browser-to-Tally XML.
(() => {
  const form=document.getElementById('tallyConnectionForm');
  const probe=document.getElementById('tallyProbe');
  const status=document.getElementById('tallyConnectionStatus');
  const dialog=document.getElementById('businessConnections');
  const top=document.getElementById('businessConnectionTop');
  top.lastChild.textContent=' Connection settings';
  let generation=0, saved=null, pollBusy=false, verifyBusy=false, lastVerify=0, pendingDiscovery=false;
  const readStatus=document.getElementById('tallyReadStatus');
  const access=document.getElementById('tallyCompanyAccess');
  const companyList=document.getElementById('tallyCompanyList');
  const pair=document.getElementById('tallyPairForm');
  const installStep=document.getElementById('tallyInstallStep');
  const showCode=()=>{installStep.hidden=true;pair.hidden=false;pair.elements.code.focus();};
  document.getElementById('tallyHaveCode').addEventListener('click',showCode);
  document.getElementById('tallyChangeComputer').addEventListener('click',showCode);
  let approved=[], discovered=[];
  const readMode=()=>document.getElementById('tallyLocal').checked?'local':'helper';
  const stateLabels={setup_needed:'Setup needed',connector_offline:'Connector offline',tally_closed:'Tally closed',
    tally_unreachable:'Tally unreachable',company_unavailable:'Company unavailable',company_approval_needed:'Choose companies',
    checking:'Checking live connection',live_available:'Live available',update_required:'Update required'};
  function showConnectionBadge(data) {
    top.lastChild.textContent=' '+(stateLabels[data.connection_state] || (data.online?'Connector online':'Connector offline'));
    top.title='Connector connection and live Tally availability are checked separately.';
  }
  function paintStatus(data) {
    showConnectionBadge(data);
    const messages={setup_needed:'Complete installation and pairing once.',connector_offline:'Connector offline. Open Windows Start → Philixa Tally Connector. If missing, download below.',
      tally_closed:'Connector online. Tally band hai; khulte hi automatically retry hoga.',
      tally_unreachable:'Connector online, lekin Tally HTTP server reachable nahi. Tally server configuration check karein.',
      company_unavailable:'Tally reachable, lekin approved company loaded nahi. Company Tally mein load karein.',
      company_approval_needed:'PC paired. Ab companies select karke approve karein.',
      checking:'Company reachable. Live stock access verify kar rahe hain…',
      live_available:'Setup complete. Live stock access verified; connection automatic rahega.',
      update_required:'Updated Tally Connector install karein. Existing pairing dobara karni zaroori nahi.'};
    readStatus.textContent=messages[data.connection_state] || 'Connection status unknown.';
    if(data.diagnostics && !data.diagnostics.startup_configured)readStatus.textContent+=data.diagnostics.package_kind==='msix'?' Automatic startup off hai; Windows Startup Apps mein status check karein.':' Automatic startup incomplete; installer dobara run karein.';
    const download=document.getElementById('tallyDownload');
    const storeUrl=data.distribution?.channel==='store'?data.distribution.url:null;
    download.hidden=!(storeUrl || data.installer_url) || !data.can_configure;
    download.textContent=(data.helper_update_required || data.customer_ledger_update_required || data.diagnostics_update_required || data.connection_state==='update_required')?'Download updated Tally Connector':'Download Tally Connector';
    if(data.customer_ledger_update_required)readStatus.textContent+=' Customer ko Tally ledger mein save karne ke liye Connector update chahiye; existing pairing retained rahegi.';
    download.dataset.channel=storeUrl?'store':'legacy';
    if(storeUrl)download.textContent='Get Tally Connector from Microsoft Store';
    download.dataset.paired=String(data.paired);download.dataset.url=storeUrl || data.installer_url || '';
    document.getElementById('tallyPurchaseSetup').hidden=!data.can_configure||!data.companies?.length;
    document.getElementById('tallyVerifySetup').hidden=!data.paired || !data.online;
  }
  async function verifySetup(id=generation) {
    if(verifyBusy)return;
    verifyBusy=true;lastVerify=Date.now();
    try {const data=await api('/setup/check','POST',{});if(id===generation)paintStatus(data);}
    catch(error){if(id===generation)readStatus.textContent='Live check incomplete: '+error.message;}
    finally{verifyBusy=false;}
  }
  document.getElementById('tallyVerifySetup').addEventListener('click',()=>verifySetup());
  async function refreshConnectionBadge() {
    if(pollBusy || document.hidden || !document.getElementById('authModal').classList.contains('hidden'))return;
    pollBusy=true;const id=generation;
    try {
      const data=await api('/helper/status');if(id!==generation)return;
      if(dialog.open)paintStatus(data);else showConnectionBadge(data);
      if(pendingDiscovery && data.online && dialog.open){pendingDiscovery=false;document.getElementById('tallyDiscover').click();}
      if(data.connection_state==='checking' && Date.now()-lastVerify>60000)await verifySetup(id);
    }catch(error){if(id===generation)top.lastChild.textContent=' Connection status unavailable';}
    finally{pollBusy=false;}
  }
  async function loadReadStatus(id=generation) {
    const data=await api('/helper/status'); if(id!==generation)return;
    approved=data.companies;
    readStatus.textContent=data.paired ? (data.online?'PC connected.':'PC offline. Philixa Tally Connector kholein.')+(approved.length?' Companies: '+approved.map(c=>c.name).join(', '):' Ab companies choose karein.') : 'First-time setup';
    if(data.helper_update_required)readStatus.textContent+=' Saved stock aur purchase sync ke liye Philixa Tally Connector update karein. Pairing dobara zaroori nahi.';
    showConnectionBadge(data);
    pair.hidden=true;
    installStep.hidden=!data.can_configure || data.paired;
    document.getElementById('tallyDiscover').hidden=!data.can_configure || !data.paired;
    document.getElementById('tallyChangeComputer').hidden=!data.can_configure || !data.paired;
    document.getElementById('tallyReplaceLabel').hidden=!data.paired;
    if(!data.can_configure)readStatus.textContent+=' Connection ke liye workspace owner/admin se kahen.';
    document.getElementById('tallyRevoke').hidden=!data.can_configure || !data.paired;
    document.getElementById('tallyLocalLabel').hidden=!data.can_configure || !data.local_available;
    paintStatus(data);
    if(!data.can_configure)readStatus.textContent+=' Setup ke liye workspace owner/admin se kahen.';
  }
  let downloadBusy=false;
  document.getElementById('tallyDownload').addEventListener('click',async()=>{
    if(downloadBusy)return;
    const button=document.getElementById('tallyDownload');
    downloadBusy=true;button.disabled=true;
    readStatus.textContent='Connector download check ho raha hai…';
    try {
      const url=button.dataset.url;
      if(url.startsWith('/')&&!url.startsWith('//')) {
        // Refresh an expired session and check access without buffering the 75 MB installer.
        const response=await window.fetchWithAuth(url,{method:'HEAD'});
        if(!response.ok)throw new Error(response.status===403?'Workspace owner/admin hi Connector download kar sakta hai.':'Connector download unavailable (HTTP '+response.status+'). Dobara login karke try karein.');
        const link=document.createElement('a');link.href=url;link.download='PhilixaTallyConnectorSetup.exe';
        document.body.append(link);link.click();link.remove();
      } else if(new URL(url).protocol==='https:') {
        const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener';document.body.append(link);link.click();link.remove();
      } else throw new Error('Connector download URL invalid.');
      installStep.hidden=false;
      readStatus.textContent=button.dataset.channel==='store'?'Microsoft Store opened. Install/update, then open Philixa Tally Connector. Pairing stays on this PC.':'Download requested. Chrome Downloads (Ctrl+J) kholo aur PhilixaTallyConnectorSetup.exe chalao → Install & continue. Download ka matlab installation complete nahi hai.';
      if(document.getElementById('tallyDownload').dataset.paired!=='true')pair.hidden=false;
    }catch(error){readStatus.textContent=error.message;}
    finally{downloadBusy=false;button.disabled=false;}
  });
  async function readAction(action) {
    const id=generation;
    try {await action(id);}catch(error){if(id===generation)readStatus.textContent=error.message;}
  }
  pair.addEventListener('submit',event=>{event.preventDefault();readAction(async id=>{
    await api('/pairing/claim','POST',{code:pair.elements.code.value.trim().toUpperCase(),replace:pair.elements.replace.checked});
    if(id!==generation)return;pair.reset();await loadReadStatus(id);pendingDiscovery=true;await refreshConnectionBadge();
  });});
  document.getElementById('tallyRevoke').addEventListener('click',()=>{
    if(!window.confirm('PC disconnect karein? Stock reads ruk jayengi.'))return;
    readAction(async id=>{await api('/helper','DELETE');await loadReadStatus(id);});
  });
  document.getElementById('tallyDiscover').addEventListener('click',()=>readAction(async id=>{
    readStatus.textContent='Tally ki companies dhoondh rahe hain…';
    const data=await api('/companies/discover?mode='+readMode());if(id!==generation)return;
    const membersResponse=await window.fetchWithAuth('/api/v1/workspaces/members');
    if(!membersResponse.ok)throw new Error('Workspace members load nahi hue. Dobara try karein.');
    const members=(await membersResponse.json()).filter(m=>m.status==='active' && m.role==='member');if(id!==generation)return;
    discovered=data.companies; companyList.replaceChildren();access.hidden=false;document.getElementById('tallyDiscover').hidden=true;
    discovered.forEach((c,index)=>{
      const old=approved.find(a=>a.identity===c.identity && a.name===c.name);
      const label=document.createElement('label');label.className='tally-checkbox';const check=document.createElement('input');check.type='checkbox';check.name='company';check.value=String(index);check.checked=!!old;
      check.disabled=discovered.filter(x=>x.identity===c.identity).length!==1 || discovered.filter(x=>x.name===c.name).length!==1;
      if(check.disabled)check.checked=false;
      label.append(check,document.createTextNode(c.name));companyList.append(label);
      const advanced=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Other names / team access (optional)';advanced.append(summary);
      const aliases=document.createElement('input');aliases.dataset.aliases=String(index);aliases.placeholder='Company ke other names, comma separated';aliases.value=old?.aliases.join(', ') || '';advanced.append(aliases);
      members.forEach(m=>{const memberLabel=document.createElement('label');memberLabel.className='tally-checkbox';const grant=document.createElement('input');grant.type='checkbox';grant.dataset.memberCompany=String(index);grant.value=m.user_id;grant.checked=old?.member_ids.includes(m.user_id) || false;memberLabel.append(grant,document.createTextNode(m.email));advanced.append(memberLabel);});
      companyList.append(advanced);
    });
    readStatus.textContent=discovered.length?'Companies select karke ek baar approve karein. Nayi company automatic access nahi paayegi.':'Company unavailable: Tally mein company load karein.';
  }));
  access.addEventListener('submit',event=>{event.preventDefault();readAction(async id=>{
    const split=value=>value.split(',').map(x=>x.trim()).filter(Boolean);
    const companies=[...companyList.querySelectorAll('input[name=company]:checked')].map(x=>({...discovered[Number(x.value)],aliases:split(companyList.querySelector(`[data-aliases="${x.value}"]`).value),member_ids:[...companyList.querySelectorAll(`[data-member-company="${x.value}"]:checked`)].map(m=>m.value)}));
    const result=await api('/companies','PUT',{mode:readMode(),companies});if(id!==generation)return;
    await loadReadStatus(id);readStatus.textContent=companies.length?'Companies approved. Live stock access check ho raha hai…':result.response;access.hidden=true;if(companies.length)await verifySetup(id);
  });});
  async function api(path,method='GET',body) {
    const response=await window.fetchWithAuth('/api/v1/integrations/tally'+path,{
      method,headers:{'Content-Type':'application/json'},...(body ? {body:JSON.stringify(body)} : {})});
    const data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==='string' ? data.detail : 'Tally request fail hui.');
    return data;
  }
  function options(key,values,preferred) {
    const control=form.elements.namedItem(key); control.replaceChildren();
    values.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value||'Select…';control.append(option);});
    if(values.includes(preferred)) control.value=preferred;
  }
  async function loadMasters() {
    const id=++generation;
    form.querySelector('button').disabled=true;
    ['godown','purchase_ledger','sales_ledger'].forEach(key=>options(key,[]));
    try {
      const company=form.elements.company.value;
      if(!company) throw new Error('Tally mein test company load karein.');
      const data=await api('/test','POST',{company}); if(id!==generation) return;
      const prior=saved?.company===company?saved:null;
      options('godown',data.godowns,prior?.godown);
      options('purchase_ledger',data.purchase_ledgers.length>1&&!data.purchase_ledgers.includes(prior?.purchase_ledger)?['',...data.purchase_ledgers]:data.purchase_ledgers,prior?.purchase_ledger);
      options('sales_ledger',data.sales_ledgers,prior?.sales_ledger);
      const ready=(data.non_gst || data.gst_configuration_supported) && data.godowns.length===1 && data.purchase_ledgers.length && data.sales_ledgers.length;
      form.querySelector('button').disabled=!ready;
      status.textContent=ready ? 'Connection reachable. Company aur ledger mappings check karke save karein.' : 'Single-godown test company aur supported purchase/sales masters chahiye.';
    } catch(error) {if(id===generation) status.textContent=error.message;}
  }
  window.openBusinessTally=async()=>{
    const id=++generation; form.hidden=true;probe.disabled=true;status.textContent='Configuration load ho rahi hai…';
    readStatus.textContent='Connection status load ho raha hai…';
    pair.hidden=true;
    installStep.hidden=true;access.hidden=true;
    ['tallyDiscover','tallyRevoke','tallyDownload','tallyLocalLabel','tallyChangeComputer','tallyVerifySetup'].forEach(key=>document.getElementById(key).hidden=true);
    try { await loadReadStatus(id); }
    catch(error) {if(id===generation)readStatus.textContent=error.message;}
    if(id!==generation)return;
    try {
      const data=await api('');if(id!==generation) return;
      saved=data.connection;probe.disabled=!data.can_configure;
      status.textContent=data.configured ? `Configured: ${saved.company}. Connection check se reachability verify karein.` : 'Abhi Tally configure nahi hua.';
      if(!data.can_configure) status.textContent+=' Setup ke liye workspace owner/admin se kahen.';
    }catch(error){if(id===generation) status.textContent=error.message;}
  };
  async function preparePurchaseSetup(preferredCompany){
    const id=++generation;probe.disabled=true;form.hidden=true;status.textContent='Tally connection check ho raha hai…';
    try {
      const data=await api('/test','POST',{});if(id!==generation)return;
      if(preferredCompany&&!data.companies.includes(preferredCompany))throw new Error('Company access badal gaya. Approved company select karein.');
      const preferred=preferredCompany||(data.companies.includes(saved?.company)?saved.company:null);
      options('company',data.companies,preferred);form.elements.test_company.checked=false;form.hidden=false;
      if(!preferred&&data.companies.length!==1){options('company',['',...data.companies]);status.textContent='Purchase ke liye approved practice company select karein.';return;}
      await loadMasters();
    }catch(error){if(id===generation)status.textContent=error.message;}
    finally{if(dialog.open)probe.disabled=false;}
  }
  probe.addEventListener('click',()=>preparePurchaseSetup());
  let purchaseSetupBusy=false;
  window.openBusinessPurchaseSetup=async companyName=>{
    if(purchaseSetupBusy)return;
    purchaseSetupBusy=true;
    const setupButton=document.getElementById('tallyPurchaseSetup');
    const advanced=document.getElementById('tallyAdvanced');
    if(!dialog.open)dialog.showModal();
    advanced.open=true;
    setupButton.disabled=true;
    setupButton.textContent='Purchase settings load ho rahi hain…';
    status.textContent='Purchase settings load ho rahi hain…';
    status.scrollIntoView({block:'nearest'});
    try {
      await window.openBusinessTally();
      if(probe.disabled){
        readStatus.textContent='Purchase setup nahi khul saka: '+status.textContent;
        return;
      }
      await preparePurchaseSetup(typeof companyName==='string'?companyName:null);
    }catch(error){status.textContent='Purchase setup load nahi hua: '+error.message;}
    finally{
      purchaseSetupBusy=false;setupButton.disabled=false;setupButton.textContent='Purchase entry setup';
    }
  };
  document.getElementById('tallyPurchaseSetup').addEventListener('click',()=>window.openBusinessPurchaseSetup());
  form.elements.company.addEventListener('change',()=>{form.elements.test_company.checked=false;return loadMasters();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();const id=++generation;const button=form.querySelector('button');button.disabled=true;
    try {
      const payload=Object.fromEntries(new FormData(form));payload.test_company=form.elements.test_company.checked;
      const result=await api('','PUT',payload);if(id!==generation)return;
      saved=payload;status.textContent=result.response;button.textContent='Connection saved ✓';
      top.lastChild.textContent=' Tally configured';
    }catch(error){if(id===generation)status.textContent=error.message;}
    finally{if(id===generation){button.disabled=false;status.scrollIntoView({block:'nearest'});}}
  });
  const reset=()=>{generation++;saved=null;pendingDiscovery=false;lastVerify=0;approved=[];discovered=[];access.hidden=true;companyList.replaceChildren();pair.reset();form.hidden=true;dialog.close();top.lastChild.textContent=' Connection settings';};
  document.getElementById('workspaceSelect')?.addEventListener('change',()=>{reset();refreshConnectionBadge();});
  new MutationObserver(()=>{if(!document.getElementById('authModal').classList.contains('hidden')) reset();else refreshConnectionBadge();})
    .observe(document.getElementById('authModal'),{attributes:true,attributeFilter:['class']});
  dialog.addEventListener('close',()=>{generation++;});
  refreshConnectionBadge();
  setInterval(refreshConnectionBadge,10000);
  document.addEventListener('visibilitychange',refreshConnectionBadge);
  window.renderBusinessTally=(tools,data,{submit,toolButton,connect,renderResult,updateMessage,updateState})=>{
    const hasIdentityBlockers=(data.issues||[]).some(i=>i.kind==='identity');
    const singleCard=!!(data.task_id&&(data.proposal||data.preview));
    if(singleCard){
      const panel=document.createElement('section');panel.className='purchase-task-panel'+(hasIdentityBlockers?' has-blockers':'');
      panel.setAttribute('aria-label','Purchase task');panel.setAttribute('aria-live','polite');
      tools.append(panel);tools=panel;
    }
    if(data.mcp_catalog){
      const label=document.createElement('label');label.textContent='Tally report';
      const select=document.createElement('select');
      data.mcp_catalog.forEach(c=>{const option=document.createElement('option');option.value=c.tool;option.textContent=c.label;select.append(option);});
      label.append(select);tools.append(label);
      toolButton(tools,'Open report',()=>submit(select.selectedOptions[0].textContent,false,{intent:'mcp_read',fields:{mcp_tool:select.value}}));
      toolButton(tools,'New operation drafts',()=>submit('New Tally operation draft',false,{intent:'mcp_write'}));
    }
    if(data.mcp_write_catalog){
      const select=document.createElement('select');select.setAttribute('aria-label','Tally operation draft');
      data.mcp_write_catalog.forEach(c=>{const option=document.createElement('option');option.value=c.tool;option.textContent=c.label;select.append(option);});tools.append(select);
      toolButton(tools,'Prepare draft',()=>submit(select.selectedOptions[0].textContent,false,{intent:'mcp_write',fields:{mcp_tool:select.value}}));
    }
    if(data.mcp_write_form){
      const spec=data.mcp_write_form, entry=document.createElement('form');entry.className='business-tool-form';
      const title=k=>k.replace(/([a-z])([A-Z])/g,'$1 $2').replaceAll('_',' ');
      const field=(parent,key,schema,required,value,depth=0)=>{
        if(depth>8)throw new Error('Operation form too nested');
        const wrapper=document.createElement('fieldset');const legend=document.createElement('legend');legend.textContent=title(key);wrapper.append(legend);parent.append(wrapper);
        if(schema.type==='object'){
          const readers={};const optional=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Optional details';optional.append(summary);wrapper.append(optional);
          Object.entries(schema.properties||{}).forEach(([k,s])=>{const req=schema.required?.includes(k)||false;readers[k]=field(req?wrapper:optional,k,s,req,value?.[k],depth+1);});
          return ()=>{const obj={};Object.entries(readers).forEach(([k,read])=>{const v=read();if(v!==undefined)obj[k]=v;});return Object.keys(obj).length||required?obj:undefined;};
        }
        if(schema.type==='array'){
          const rows=[];const add=val=>{const row=document.createElement('div');wrapper.append(row);const reader=field(row,'Entry',schema.items,true,val,depth+1);rows.push({row,reader});
            const remove=document.createElement('button');remove.type='button';remove.textContent='Remove entry';remove.onclick=()=>{row.remove();rows.splice(rows.findIndex(x=>x.row===row),1);};row.append(remove);};
          (value||[]).forEach(add);if(required&&!rows.length)add();
          const button=document.createElement('button');button.type='button';button.textContent='Add entry';button.onclick=()=>{if(rows.length<50)add();};wrapper.append(button);
          return ()=>rows.length?rows.map(x=>x.reader()):required?[]:undefined;
        }
        const control=schema.enum?document.createElement('select'):document.createElement('input');
        if(schema.enum){const blank=document.createElement('option');blank.value='';blank.textContent='Select';control.append(blank);schema.enum.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;control.append(o);});}
        else control.type=schema.type==='boolean'?'checkbox':schema.type==='number'||schema.type==='integer'?'number':'text';
        if(schema.type==='boolean')control.checked=value??schema.default??false;
        else {control.value=value??schema.default??'';control.required=required;control.maxLength=2000;if(control.type==='number'){control.step=schema.type==='integer'?'1':'any';if(schema.minimum!==undefined)control.min=schema.minimum;}}
        control.setAttribute('aria-label',title(key));wrapper.append(control);
        return ()=>{if(schema.type==='boolean')return control.checked?true:required||value!==undefined?false:undefined;if(control.value==='')return undefined;
          if(schema.type==='number'||schema.type==='integer'){if(control.value.replace(/[^0-9]/g,'').length>15)throw new Error(title(key)+': number has too much precision');return Number(control.value);}return control.value;};
      };
      const read=field(entry,spec.label,spec.schema,true,spec.fields.mcp_arguments);
      const error=document.createElement('p');error.setAttribute('role','alert');entry.append(error);
      const button=document.createElement('button');button.type='submit';button.textContent='Save draft';entry.append(button);
      entry.addEventListener('submit',event=>{event.preventDefault();try{submit(spec.label,false,{intent:'mcp_write',fields:{...spec.fields,mcp_arguments:read()}});}catch(e){error.textContent=e.message;}});tools.append(entry);
    }
    if(data.mcp_form){
      const spec=data.mcp_form, entry=document.createElement('form');entry.className='business-tool-form';
      const titles={from:'From date',to:'To date',asOf:'As of date',ledgerName:'Exact Tally ledger name',query:'Ledger name (optional)'};
      Object.entries(spec.schema.properties).forEach(([key,definition])=>{
        const label=document.createElement('label');label.textContent=titles[key]||key;
        const control=document.createElement('input');control.name=key;
        control.type=['from','to','asOf'].includes(key)?'date':'text';control.required=spec.schema.required?.includes(key)||false;
        const value=spec.fields.mcp_arguments?.[key];control.value=value?String(value).replace(/^(\d{2})-(\d{2})-(\d{4})$/,'$3-$2-$1'):'';
        control.maxLength=200;label.append(control);entry.append(label);
      });
      const button=document.createElement('button');button.type='submit';button.textContent='Read '+spec.label;entry.append(button);
      entry.addEventListener('submit',event=>{event.preventDefault();const args=Object.fromEntries([...new FormData(entry)].filter(([,v])=>v!==''));
        submit(spec.label,false,{intent:'mcp_read',fields:{...spec.fields,mcp_arguments:args}});});tools.append(entry);
    }
    if(data.mcp_report){
      const report=data.mcp_report, panel=document.createElement('div');panel.className='business-report';
      const info=document.createElement('p');info.textContent=`${report.company} · Live read ${new Date(report.read_at).toLocaleString()} · ${report.total_rows} rows`;panel.append(info);
      const period=report.arguments?.from&&report.arguments?.to?`${report.arguments.from} to ${report.arguments.to}`:'';
      const title=document.createElement('p');title.textContent=report.title;panel.append(title);
      if(period){const range=document.createElement('p');range.textContent='Date range: '+period;panel.append(range);}
      const search=document.createElement('input');search.type='search';search.placeholder='Search this report';search.setAttribute('aria-label','Search report');panel.append(search);
      const wrap=document.createElement('div');wrap.style.overflowX='auto';wrap.style.maxHeight='400px';
      const table=document.createElement('table');const head=document.createElement('thead');const tr=document.createElement('tr');
      report.columns.forEach(c=>{const th=document.createElement('th');th.textContent=c.replaceAll('_',' ');th.scope='col';tr.append(th);});head.append(tr);table.append(head);
      const body=document.createElement('tbody');table.append(body);wrap.append(table);panel.append(wrap);
      const count=document.createElement('p');panel.append(count);
      const draw=()=>{const matches=report.rows.filter(row=>row.some(v=>String(v).toLocaleLowerCase().includes(search.value.toLocaleLowerCase())));body.replaceChildren();
        matches.slice(0,200).forEach(row=>{const tr=document.createElement('tr');row.forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td);});body.append(tr);});
        count.textContent=`Showing ${Math.min(matches.length,200)} of ${matches.length} matching rows.${report.truncated?' Report limited to 2000 rows; choose a narrower date range.':''}`;};search.addEventListener('input',draw);draw();
      if(report.note){const note=document.createElement('p');note.textContent=report.note;panel.append(note);}
      toolButton(panel,'Download CSV',()=>{
        const metadata=[['Report',report.title],['Company',report.company],['Date range',period],['Live read',report.read_at]];
        if(report.note)metadata.push(['Note',report.note]);
        const csv=[...metadata,[],report.columns,...report.rows].map(row=>row.map(v=>'"'+String(v).replace(/^[=+@\-]/,"'$&").replaceAll('"','""')+'"').join(',')).join('\r\n');
        const url=URL.createObjectURL(new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=report.title.replace(/[^a-z0-9]+/gi,'-')+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      });tools.append(panel);
    }
    if(data.stock_results){
      const details=document.createElement('p');
      details.textContent=data.stock_results.filter(r=>r.read_at||r.last_synced_at).map(r=>`${r.company}: ${r.data_source==='saved'?'Last synced':'Live read'} ${new Date(r.last_synced_at||r.read_at).toLocaleString()}`).join(' · ');
      tools.append(details);
      data.stock_results.filter(r=>r.data_source==='saved').forEach(r=>toolButton(tools,'Sync '+r.company,async()=>{
        const result=document.createElement('p');tools.append(result);
        try{const response=await api('/companies/'+encodeURIComponent(r.company_id)+'/refresh','POST',{});result.textContent=response.response;}
        catch(error){result.textContent=error.message;}
      }));
    }
    if(data.purchase_setup)toolButton(tools,'Purchase entry setup',()=>window.openBusinessPurchaseSetup(data.purchase_setup.company));
    else if(data.connect_tally)toolButton(tools,'Connect Tally',connect);
    if(data.proposal){
      const proposal=data.proposal;
      const card=document.createElement('section');
      if(singleCard&&hasIdentityBlockers){
        const details=document.createElement('details');
        details.className='purchase-proposal-toggle';
        const summary=document.createElement('summary');
        summary.textContent=`🔍 Tally calculation & raw lines (${proposal.content?.lines?.length||0} items)`;
        details.append(summary);
        card.className='purchase-proposal purchase-proposal-collapsed';
        details.append(card);
        tools.append(details);
      }else{
        card.className='purchase-proposal';
        tools.append(card);
      }
      const heading=document.createElement('strong');heading.textContent='Purchase review · '+proposal.company;card.append(heading);
      const party=document.createElement('p');party.textContent=proposal.content.party_name||(data.repeat_purchase?'Suggested supplier: '+data.repeat_purchase.supplier:'Supplier select karein');card.append(party);
      proposal.content.lines.forEach((line,index)=>{
        const p=document.createElement('p');
        const suggested=(data.suggestions||[]).find(s=>s.field===index+':rate');
        p.textContent=[line.item_name||'Item pending',line.quantity&&`${line.quantity} ${line.unit||''}`,
          line.rate?`₹${line.rate} per ${line.unit||'unit'}`:suggested?`Suggested ₹${suggested.value} — ${suggested.entry_date}`:'Rate pending'].filter(Boolean).join(' · ');
        card.append(p);
      });
      if(proposal.content.invoice_number||proposal.content.entry_date){const p=document.createElement('p');p.textContent=[proposal.content.invoice_number,proposal.content.entry_date].filter(Boolean).join(' · ');card.append(p);}
      if(proposal.totals.total){const p=document.createElement('p');p.textContent='Calculated before tax: ₹'+proposal.totals.total;card.append(p);}
      if(proposal.content.invoice_total){const p=document.createElement('p');p.textContent='User/source invoice total: ₹'+proposal.content.invoice_total;card.append(p);}
      if(data.repeat_purchase){
        const repeat=document.createElement('p');repeat.className='purchase-repeat-summary';
        repeat.textContent=(data.repeat_purchase.subtotal_before_discount_tax?'Is nayi purchase ka suggested subtotal ₹'+data.repeat_purchase.subtotal_before_discount_tax+' (discount/GST se pehle). ':'')+data.repeat_purchase.note;
        card.append(repeat);
      }
      if(data.purchase_context?.status&&data.purchase_context.status!=='ready'){
        const p=document.createElement('p');p.textContent=data.purchase_context.reason||'Tally context sync pending; abhi entry ready nahi hai.';card.append(p);
      }else if(data.purchase_context?.collected_at){const p=document.createElement('p');p.textContent='Tally context checked: '+data.purchase_context.collected_at;card.append(p);}
      const notes=document.createElement('details');const title=document.createElement('summary');title.textContent='Sources aur checks';notes.append(title);
      Object.entries(proposal.provenance||{}).forEach(([field,source])=>{const p=document.createElement('p');p.textContent=`${field}: ${source.value} · ${source.source_type} · ${source.status}`;notes.append(p);});
      (data.issues||[]).forEach(issue=>{const p=document.createElement('p');p.textContent=issue.message;notes.append(p);});card.append(notes);
      if(data.suggestions?.length&&!data.task_id)toolButton(tools,'Suggested rates sahi hain',()=>submit('Suggested rates sahi hain',false,{purchase_reply:{...data.purchase_assistant,accept_suggestions:true,evidence_version:data.evidence_version}}));
      if(data.task_id)(data.selections||[]).filter(o=>o.kind==='rate').forEach(offer=>{
        toolButton(tools,'Is purchase ka rate ₹'+offer.value+' hai',()=>submit('Suggested rate ₹'+offer.value+' is purchase ke liye confirm hai',false,
          {selection:{reference:offer.reference,draft_revision:offer.draft_revision,evidence_version:offer.evidence_version}}));
      });
      if(proposal.can_prepare_preview)toolButton(tools,'Validate & show final preview',()=>submit('Final preview',false,{purchase_reply:{...data.purchase_assistant,prepare_preview:true,evidence_version:data.evidence_version}}));
      if(!singleCard&&data.status!=='waiting_context'&&!data.issues?.some(i=>i.kind==='identity'))toolButton(tools,'Refresh Tally context',async()=>{
        try{
          if(data.task_id){await submit('Tally context refresh',false,{context_refresh:true});return;}
          const response=await window.fetchWithAuth('/api/v1/business/purchase-drafts/'+data.draft_id+'/context-refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
          const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Context refresh unavailable.');
          await submit('Context status',false,{purchase_reply:{draft_id:data.draft_id,resume:true}});
        }
        catch(error){const p=document.createElement('p');p.textContent=error.message;tools.append(p);}
      });
      if(!data.task_id&&['queued','processing','stale'].includes(data.purchase_context?.status))toolButton(tools,'Check context status',()=>submit('Context status',false,{purchase_reply:{draft_id:data.draft_id,resume:true}}));
    }
    if(data.purchase_assistant)tools.classList.add('purchase-chat-layout');
    const historyHint=data.purchase_context?.supplier_suggestion;
    if(historyHint&&data.purchase_assistant){
      tools.classList.add('purchase-history-controls');
      const text=(data.response||'').split('\n').filter(line=>!line.startsWith('Pichhli matching Tally purchase:')).join('\n');
      if(text)updateMessage?.(text);
      const card=document.createElement('section');card.className='purchase-history-card';card.setAttribute('aria-label','Tally history suggestion');
      const label=document.createElement('span');label.className='purchase-history-label';label.textContent='Pichhli purchase se suggestion';card.append(label);
      const supplier=document.createElement('strong');supplier.textContent=historyHint.supplier;card.append(supplier);
      (historyHint.rates||[]).forEach(rate=>{
        const row=document.createElement('div');row.className='purchase-history-rate';
        const price=document.createElement('strong');price.textContent='Rate ₹'+Number(rate.value).toLocaleString('en-IN',{maximumFractionDigits:2});
        const date=document.createElement('span');const stamp=rate.entry_date?.split('-');date.textContent=stamp?.length===3?'Purchase: '+stamp.reverse().join('-'):rate.entry_date||'';
        row.append(price,date);card.append(row);
      });
      const prompt=document.createElement('p');prompt.textContent='Is baar bhi supplier aur rate wahi hain?';card.append(prompt);
      const accept=toolButton(card,'Haan, wahi hain',()=>{
        if(data.task_id){
          const offer=(data.selections||[]).find(o=>o.kind==='history');
          if(offer)return submit('Haan, wahi supplier/rate hain',false,{selection:{reference:offer.reference,draft_revision:offer.draft_revision,evidence_version:offer.evidence_version}});
          const facts=(historyHint.rates||[]).map(rate=>{
            const index=Number(rate.field.split(':')[0]);const line=data.proposal.content.lines[index];
            return `${line.item_name}: rate ${rate.value}`;
          }).join('; ');
          return submit(`Supplier: ${historyHint.supplier}. ${facts}. Ye dikhaye gaye suggested supplier/rate is purchase ke liye confirm hain.`);
        }
        return submit('Haan, supplier aur rates wahi hain',false,{purchase_reply:data.purchase_assistant});
      });accept.classList.add('purchase-history-confirm');
      const alternatives=document.createElement('details');alternatives.className='purchase-history-alternatives';
      const title=document.createElement('summary');title.textContent='Supplier ya rate badalna hai';alternatives.append(title);
      const options=document.createElement('div');options.className='purchase-history-options';alternatives.append(options);
      (data.purchase_assistant.choices||[]).filter(choice=>choice!=='Haan, supplier aur rates wahi hain').forEach(choice=>toolButton(options,choice,()=>submit(choice,false,{purchase_reply:data.purchase_assistant})));
      card.append(alternatives);tools.append(card);
    }else if(data.purchase_assistant?.choices?.length&&(!singleCard||data.status!=='waiting_context')){
      const options=document.createElement('section');options.className='purchase-choice-card';
      options.setAttribute('aria-label',data.purchase_assistant.field==='party_name'?'Supplier selection':'Purchase options');
      if(data.purchase_assistant.field==='party_name'){
        const heading=document.createElement('strong');heading.textContent='Kis supplier se kharida?';options.append(heading);
        const text=(data.response||'').split('\n').filter(line=>!line.startsWith('Kis supplier se kharida?')).join('\n');
        if(text)updateMessage?.(text);
      }
      const choices=document.createElement('div');choices.className='purchase-choice-list';options.append(choices);
      if(data.purchase_assistant.field?.endsWith(':item_name')){
        toolButton(choices,'🔗 Existing item se map karein',()=>submit('Existing item se map karna hai'));
        toolButton(choices,'🔄 Tally items sync karein',()=>submit('Tally items sync karo'));
        if(data.purchase_assistant.choices?.length){
          const existDetails=document.createElement('details');existDetails.className='purchase-history-alternatives';
          const existSummary=document.createElement('summary');existSummary.textContent='Existing stock items me se chunein';existDetails.append(existSummary);
          const existOpts=document.createElement('div');existOpts.className='purchase-choice-list';existDetails.append(existOpts);
          data.purchase_assistant.choices.forEach(choice=>{
            toolButton(existOpts,choice,()=>{
              const offer=(data.selections||[]).find(o=>o.kind==='identity'&&o.value===choice);
              if(data.task_id&&offer)return submit(choice,false,{selection:{reference:offer.reference,draft_revision:offer.draft_revision,evidence_version:offer.evidence_version}});
              return submit(`${data.purchase_assistant.field}: ${choice}`);
            });
          });
          options.append(existDetails);
        }
      }else{
        data.purchase_assistant.choices.forEach(choice=>{
          const isSuggestedRate=data.purchase_assistant.field?.endsWith(':rate')&&(data.purchase_context?.suggestions||[]).some(s=>s.field===data.purchase_assistant.field&&s.value===choice);
          const label=isSuggestedRate?'Haan, ₹'+Number(choice).toLocaleString('en-IN',{maximumFractionDigits:2})+' rate':choice;
          toolButton(choices,label,()=>{
            const offer=(data.selections||[]).find(o=>o.kind==='identity'&&o.value===choice);
            if(data.task_id&&offer)return submit(choice,false,{selection:{reference:offer.reference,draft_revision:offer.draft_revision,evidence_version:offer.evidence_version}});
            return submit(choice,false,{purchase_reply:data.purchase_assistant});
          });
        });
      }
      tools.append(options);
    }
    if(['pending','queued','processing','stale'].includes(data.purchase_context?.native_history_status)){
      const history=document.createElement('div');history.className='purchase-history-status';
      const text=document.createElement('span');text.textContent='Tally history check ho rahi hai.';history.append(text);
      if(!singleCard)toolButton(history,'Status dekhein',()=>submit('History status',false,{purchase_reply:{draft_id:data.draft_id,resume:true}}));tools.append(history);
    }
    if(['error','unavailable'].includes(data.purchase_context?.native_history_status)){
      const reason=document.createElement('p');reason.className='purchase-history-status';
      reason.textContent=data.purchase_context.native_history_reason||'Tally history abhi verify nahi hui. Rate khud batayein; purana rate assume nahi karunga.';tools.append(reason);
    }
    let extraTools=tools;
    const compactFacts=singleCard&&data.status==='needs_input'&&data.proposal?.content?.party_name&&!data.receipt_ready&&!hasIdentityBlockers;
    if(singleCard&&data.status==='needs_input'){
      if(data.goods_receipt){const route=document.createElement('p');route.textContent='Goods received · bill pending';tools.append(route);}
      if(!compactFacts&&!hasIdentityBlockers)(data.situation_choices||[]).forEach(choice=>toolButton(tools,choice,()=>submit(choice)));
      if(data.receipt_ready)toolButton(tools,'Receipt Note ka review',()=>submit('Receipt Note preview'));
    }
    if(compactFacts){
      const form=document.createElement('form');form.className='purchase-inline-reply';
      const heading=document.createElement('strong');heading.textContent='Bas bachi hui details ek saath confirm karein';form.append(heading);
      const facts=data.purchase_situation||{};
      const controls=[];
      function selectFact(title,options){
        const label=document.createElement('label');label.textContent=title;
        const input=document.createElement('select');input.required=true;
        [['','Chunein…'],...options].forEach(([value,text])=>{const option=document.createElement('option');option.value=value;option.textContent=text;input.append(option);});
        label.append(input);form.append(label);controls.push(()=>input.value);return input;
      }
      if(!facts.bill_status&&!data.proposal.content.invoice_number)selectFact('Bill',[['Bill baad mein','Abhi nahi mila'],['Bill mil gaya','Mil gaya hai']]);
      if(!facts.goods_status)selectFact('Maal',[['Maal aa gaya','Mil chuka hai'],['Maal abhi nahi aaya','Abhi nahi mila']]);
      if(!facts.received_on&&!data.goods_receipt?.received_on){
        const label=document.createElement('label');label.textContent='Maal milne ki date (mil chuka ho toh)';
        const date=document.createElement('input');date.type='date';label.append(date);form.append(label);
        controls.push(()=>date.value?'Received date: '+date.value:'');
      }
      if(!facts.rate_basis&&!data.goods_receipt?.rate_basis)selectFact('Dikhaye gaye rate mein GST',[['GST alag lagega','GST alag hai'],['GST included','GST included hai'],['No GST charged','Supplier ne GST charge nahi kiya']]);
      (data.proposal.content.lines||[]).forEach((line,index)=>{
        if(line.rate!=null||(data.suggestions||[]).some(s=>s.field===`${index}:rate`))return;
        const label=document.createElement('label');label.textContent=(line.item_name||'Item')+' ka actual rate';
        const rate=document.createElement('input');rate.type='number';rate.min='0.01';rate.step='0.01';rate.required=true;
        label.append(rate);form.append(label);controls.push(()=>rate.value?(line.item_name||'Item')+': rate '+rate.value:'');
      });
      const correction=document.createElement('textarea');correction.rows=1;correction.maxLength=4000;
      correction.placeholder='Rate / bill details ya koi correction (optional)';correction.setAttribute('aria-label','Purchase details or correction');form.append(correction);
      const send=document.createElement('button');send.type='submit';send.textContent='Confirm details · final review';form.append(send);
      form.addEventListener('submit',event=>{event.preventDefault();
        if(typeof form.reportValidity==='function'&&!form.reportValidity())return;
        const parts=controls.map(read=>read()).filter(Boolean);if(correction.value.trim())parts.push(correction.value.trim());
        if(parts.length)submit(parts.join('. ')+'. Details save karke available final preview dikhao.');
      });
      tools.append(form);
    }
    if(singleCard&&data.status==='needs_input'&&!compactFacts&&!hasIdentityBlockers){
      const form=document.createElement('form');form.className='purchase-inline-reply';
      const label=document.createElement('label');label.textContent=data.details_unknown?'Details milne par yahin likhein':'Missing details ya correction ek saath likhein';
      const answer=document.createElement('textarea');answer.rows=2;answer.maxLength=4000;
      answer.setAttribute('aria-label','Purchase details or correction');
      answer.placeholder=data.goods_receipt?'Received date: 02-10-2026, GST alag lagega…':'Jaise: rate 350, bill A-21, date 02-10-2026…';label.append(answer);form.append(label);
      const send=document.createElement('button');send.type='submit';send.textContent='Update review';form.append(send);
      form.addEventListener('submit',event=>{event.preventDefault();if(answer.value.trim())submit(answer.value.trim());});
      if(!data.details_unknown)toolButton(form,'Details pata nahi',()=>submit('pata nahi'));
      tools.append(form);
    }
    if(data.purchase_assistant){
      const extra=document.createElement('details');extra.className='purchase-extra-options';
      const label=document.createElement('summary');label.textContent='Bill upload aur doosre options';extra.append(label);
      extraTools=document.createElement('div');extraTools.className='purchase-extra-content';extra.append(extraTools);tools.append(extra);
      toolButton(extraTools,'Bill photo/PDF upload',()=>document.getElementById('businessDocumentsBtn').click());
    }
    if(data.purchase_details?.length){
      const details=document.createElement('details');
      const label=document.createElement('summary');label.textContent='Checks aur pending details';details.append(label);
      data.purchase_details.forEach(text=>{const p=document.createElement('p');p.textContent=text;details.append(p);});
      extraTools.append(details);
    }
    if(data.purchase_resume)toolButton(tools,'Resume purchase',()=>submit('Resume purchase',false,{purchase_reply:{draft_id:data.purchase_resume,resume:true}}));
    if(data.gst_purchase_draft&&!data.goods_receipt)toolButton(extraTools,data.purchase_assistant?'Detailed review (optional)':data.purchase_resume?'Purchase details':'GST purchase review',async()=>{
      try{
        if(typeof window.openDraftWithDoc!=='function')throw new Error('Bills screen load nahi hui. Reload karke Bills · saved drafts kholein.');
        await window.openDraftWithDoc(data.gst_purchase_draft.id);
      }catch(error){const message=document.createElement('p');message.textContent=error.message;tools.append(message);}
    });
    data.tally_choices?.forEach(choice=>toolButton(tools,choice.name,()=>submit(choice.name,false,choice.command)));
    if(data.tally_form){
      const fields=data.tally_form.fields;
      const entry=document.createElement('form');entry.className='business-tool-form';
      const count=data.tally_form.intent==='stock_count_set';
      const defs=count?[['item_name','Item','text'],['target_quantity','Actual final count','number'],['unit','Unit','text'],['counted_at','Count time (ISO, timezone ke saath)','text'],['reason','Correction reason','text']]:[['party_name','Supplier / customer','text'],['quantity','Quantity','number'],['unit','Unit (Tally base unit)','text'],['rate','Rate per unit ₹','number'],['entry_date','Purchase date','date']];
      defs.forEach(([key,title,type])=>{const label=document.createElement('label');label.textContent=title;
        const input=document.createElement('input');input.name=key;input.type=type;input.required=true;
        input.value=fields[key] ?? '';
        if(key==='counted_at'&&!input.value)input.value=new Date().toISOString();input.maxLength=200;if(type==='number'){input.min=key==='target_quantity'?'0':key==='rate'?'0.01':'0.000001';input.step=key==='rate'?'0.01':'any';}
        if(type==='date'&&!input.value){
          const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
          const part=type=>parts.find(p=>p.type===type).value;
          input.value=`${part('year')}-${part('month')}-${part('day')}`;
        }
        label.append(input);entry.append(label);});
      const note=document.createElement('p');note.textContent=count?'Final physical count likhein, add/remove quantity nahi. Offline save ke baad live review aur fresh confirmation zaroori hai.':'Tally EDU mode mein purchase date restricted ho sakti hai. Test ke liye allowed date chunein; preview mein date check karein.';entry.append(note);
      const button=document.createElement('button');button.type='submit';button.textContent='Tally preview';entry.append(button);
      entry.addEventListener('submit',event=>{event.preventDefault();submit('Tally entry details',false,{intent:data.tally_form.intent,fields:{...fields,...Object.fromEntries(new FormData(entry))}});});
      tools.append(entry);
    }
    if(data.tally_action){
      const panel=document.createElement('div');tools.append(panel);
      const update=(response,initial=false)=>{panel.replaceChildren();
        updateState?.(response);
        // The chat message and its controls share one current status. Replacing
        // just the controls left the original pending sentence visible forever.
        const message=updateMessage?.(response.response || 'Entry ka status check karein.') || document.createElement('p');
        if(!updateMessage){message.textContent=response.response;panel.append(message);}
        // The initial renderTools call already owns the preview card. Subsequent
        // refreshes render its replacement without recursively recreating an
        // action-status panel. Keep offline draft review reachable in both cases.
        if(response.preview && !initial)renderResult?.(panel,{...response,tally_action:null});
        if(response.sync_status==='verified')return;
        if(response.count_review_available)toolButton(panel,'Live count review',async()=>{
          try{update(await api('/actions/'+encodeURIComponent(data.tally_action)+'/review','POST',{}));}catch(error){message.textContent=error.message;}
        });
        if(response.mcp_review_available)toolButton(panel,'Review saved operation draft',async()=>{
          try{update(await api('/actions/'+encodeURIComponent(data.tally_action)+'/review','POST',{}));}catch(error){message.textContent=error.message;}
        });
        if(!response.preview && ['queued','draft','awaiting_review'].includes(response.sync_status))toolButton(panel,'Cancel unsubmitted entry',async()=>{
          try{update(await api('/actions/'+encodeURIComponent(data.tally_action)+'/cancel','POST',{}));}catch(error){message.textContent=error.message;}
        });
        toolButton(panel,'Status check (no resend)',async()=>{
          message.textContent='Status check ho raha hai…';
          try{update(await api('/actions/'+encodeURIComponent(data.tally_action)+'/reconcile','POST',{}));}catch(error){message.textContent=error.message;}
        });
      };update(data,true);
    }
  };
})();
