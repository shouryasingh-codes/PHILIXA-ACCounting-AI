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
    if(data.diagnostics && !data.diagnostics.startup_configured)readStatus.textContent+=' Automatic startup incomplete; installer dobara run karein.';
    const download=document.getElementById('tallyDownload');
    download.hidden=!data.installer_url || !data.can_configure;
    download.textContent=(data.helper_update_required || data.customer_ledger_update_required || data.diagnostics_update_required || data.connection_state==='update_required')?'Download updated Tally Connector':'Download Tally Connector';
    if(data.customer_ledger_update_required)readStatus.textContent+=' Customer ko Tally ledger mein save karne ke liye Connector update chahiye; existing pairing retained rahegi.';
    download.dataset.paired=String(data.paired);download.dataset.url=data.installer_url || '';
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
  document.getElementById('tallyDownload').addEventListener('click',async()=>{
    try {
      const url=document.getElementById('tallyDownload').dataset.url;
      if(url.startsWith('/')) {
        const response=await window.fetchWithAuth(url);if(!response.ok)throw new Error('Helper download unavailable');
        const blob=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=blob;link.download='PhilixaTallyConnectorSetup.exe';link.click();setTimeout(()=>URL.revokeObjectURL(blob),10000);
      } else if(new URL(url).protocol==='https:') window.open(url,'_blank','noopener');
      installStep.hidden=false;
      readStatus.textContent='Download requested. Chrome Downloads (Ctrl+J) kholo aur PhilixaTallyConnectorSetup.exe chalao → Install & continue. Download ka matlab installation complete nahi hai.';
      if(document.getElementById('tallyDownload').dataset.paired!=='true')pair.hidden=false;
    }catch(error){readStatus.textContent=error.message;}
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
    values.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;control.append(option);});
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
      options('godown',data.godowns,saved?.godown);
      options('purchase_ledger',data.purchase_ledgers,saved?.purchase_ledger);
      options('sales_ledger',data.sales_ledgers,saved?.sales_ledger);
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
  probe.addEventListener('click',async()=>{
    const id=++generation;probe.disabled=true;form.hidden=true;status.textContent='Tally connection check ho raha hai…';
    try {
      const data=await api('/test','POST',{});if(id!==generation)return;
      options('company',data.companies,saved?.company);form.hidden=false;
      await loadMasters();
    }catch(error){if(id===generation)status.textContent=error.message;}
    finally{if(dialog.open)probe.disabled=false;}
  });
  form.elements.company.addEventListener('change',loadMasters);
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
    if(data.connect_tally)toolButton(tools,'Connect Tally',connect);
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
