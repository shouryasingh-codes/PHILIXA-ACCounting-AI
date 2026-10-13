// Private originals: authenticated fetch -> temporary blob; never public object URLs.
(() => {
  const dialog=document.getElementById('businessDocuments'),company=document.getElementById('documentCompany');
  const batches=document.getElementById('documentBatch'),files=document.getElementById('documentFiles');
  const list=document.getElementById('documentList'),status=document.getElementById('documentStatus');
  const viewer=document.getElementById('documentViewer'),pageLabel=document.getElementById('documentPage');
  let scope=null,generation=0,batch=null,busy=false,poll=null,viewUrl=null,current=null,page=1;
  const scopeNow=()=>JSON.stringify(window.getBusinessChatScope?.()||null);
  const valid=id=>id===generation&&scope===scopeNow()&&dialog.open;
  const json=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  async function request(path,options={}){
    if(scope!==scopeNow())throw new Error('Workspace changed. Reopen documents.');
    const response=await window.fetchWithAuth('/api/v1/business'+path,options);
    if(!response.ok){const data=await response.json();throw new Error(typeof data.detail==='string'?data.detail:'Document request failed.');}
    return response;
  }
  const api=async(path,options)=>await (await request(path,options)).json();
  function resetViewer(){if(viewUrl)URL.revokeObjectURL(viewUrl);viewUrl=null;current=null;viewer.replaceChildren();pageLabel.textContent='';
    document.getElementById('documentPrevious').disabled=true;document.getElementById('documentNext').disabled=true;document.getElementById('documentDownload').disabled=true;}
  function setBusy(value){busy=value;files.disabled=value;document.getElementById('documentUpload').disabled=value;
    document.getElementById('documentNewBatch').disabled=value;batches.disabled=value;company.disabled=value||Boolean(batch);}
  async function preview(row,newPage=1){const id=generation;current=row;page=newPage;
    try{const path=row.media_type==='application/pdf'?'/documents/'+row.id+'/pages/'+newPage:'/documents/'+row.id+'/original';
      const blob=await (await request(path)).blob();if(!valid(id)||current?.id!==row.id||page!==newPage)return;
      if(viewUrl)URL.revokeObjectURL(viewUrl);viewUrl=URL.createObjectURL(blob);viewer.replaceChildren();
      const img=document.createElement('img');img.src=viewUrl;img.alt=row.filename+' · page '+newPage;viewer.append(img);
      pageLabel.textContent=row.filename+' · '+newPage+' / '+row.page_count;
      document.getElementById('documentPrevious').disabled=newPage<=1;
      document.getElementById('documentNext').disabled=row.media_type!=='application/pdf'||newPage>=row.page_count;
      document.getElementById('documentDownload').disabled=false;
    }catch(error){if(valid(id))status.textContent=error.message;}
  }
  async function refresh(){const id=generation;if(!batch||!valid(id))return;
    const data=await api('/document-batches/'+batch);if(!valid(id)||data.id!==batch)return;
    list.replaceChildren();
    if(!data.documents.length)list.textContent='Is batch mein abhi koi file nahi hai.';
    for(const row of data.documents){const card=document.createElement('div');card.className='document-card';
      const name=document.createElement('strong');name.textContent=row.filename;
      const state=document.createElement('p');state.textContent=row.message+(row.page_count?' · '+row.page_count+' pages':'');card.append(name,state);
      if(row.status==='ready'){
        const actions=document.createElement('div');actions.className='doc-card-actions';
        const open=document.createElement('button');open.type='button';open.textContent='View original';open.addEventListener('click',()=>preview(row));actions.append(open);
        const draftBtn=document.createElement('button');draftBtn.type='button';
        const extracting=['queued','processing'].includes(row.extraction_status);
        draftBtn.textContent=extracting?'Extraction processing...':row.extraction_status==='needs_review'?'Review extracted draft':row.extraction_status==='error'?'Retry extraction':'Extract & review draft';
        draftBtn.disabled=extracting;
        if(row.extraction_error){const error=document.createElement('p');error.textContent=row.extraction_error;card.append(error);}
        draftBtn.addEventListener('click',async()=>{
          if(busy)return;const stamp=generation;setBusy(true);
          try{
            status.textContent='Extracting invoice details...';
            const ext=await api('/documents/'+row.id+'/extract',json({}));
            if(!valid(stamp))return;
            const draftId=ext.draft?.id||ext.drafts?.[0]?.id;
            if(draftId){dialog.close();if(window.openDraftWithDoc)await window.openDraftWithDoc(draftId);}
            else{status.textContent='Extraction queued · processing will continue after reload. Open Review when ready.';await refresh();}
          }catch(error){if(valid(stamp))status.textContent=error.message;}
          finally{if(valid(stamp))setBusy(false);}
        });
        actions.append(draftBtn);card.append(actions);
      }
      if(row.retry_available){const retry=document.createElement('button');retry.type='button';retry.textContent='Retry check';retry.addEventListener('click',async()=>{
        if(busy)return;const stamp=generation;setBusy(true);try{await api('/documents/'+row.id+'/retry',json({}));if(valid(stamp))await refresh();}
        catch(error){if(valid(stamp))status.textContent=error.message;}finally{if(valid(stamp))setBusy(false);}});card.append(retry);}
      list.append(card);
    }
    clearTimeout(poll);poll=null;
    if(data.documents.some(row=>['queued','processing'].includes(row.status)||['queued','processing'].includes(row.extraction_status)))poll=setTimeout(async()=>{
      if(!valid(id))return;if(busy){poll=setTimeout(()=>{if(valid(id))refresh().catch(error=>status.textContent=error.message);},3000);return;}
      try{await refresh();}catch(error){if(valid(id)){status.textContent=error.message;poll=setTimeout(()=>{if(valid(id))refresh().catch(()=>{});},5000);}}
    },3000);
  }
  async function loadBatches(id,selectLatest=true){const data=await api('/document-batches');if(!valid(id))return;
    batches.replaceChildren();const blank=document.createElement('option');blank.value='';blank.textContent='New upload batch';batches.append(blank);
    for(const row of data.batches){const option=document.createElement('option');option.value=row.id;
      option.textContent=new Date(row.created_at).toLocaleString();option.dataset.company=row.company_id;batches.append(option);}
    if(selectLatest&&data.batches.length){batch=data.batches[0].id;company.value=data.batches[0].company_id;batches.value=batch;await refresh();}
    else if(batch)batches.value=batch;
  }
  async function open(){const id=++generation;scope=scopeNow();batch=null;resetViewer();list.replaceChildren();company.replaceChildren();setBusy(true);
    status.textContent='PDF/JPG/PNG · 10 MB per file · 20 PDF pages · 50 files per batch';
    try{const data=await api('/purchase-drafts/companies');if(!valid(id))return;
      for(const row of data.companies){const option=document.createElement('option');option.value=row.id;option.textContent=row.name;company.append(option);}
      if(!data.companies.length)status.textContent='Pehle Tally setup mein company select karein.';
      await loadBatches(id);
    }catch(error){if(valid(id))status.textContent=error.message;}finally{if(valid(id))setBusy(false);}
  }
  document.getElementById('businessDocumentsBtn').addEventListener('click',()=>{dialog.showModal();open();});
  document.getElementById('businessCloseDocuments').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{busy=false;generation++;scope=null;batch=null;clearTimeout(poll);poll=null;resetViewer();files.value='';list.replaceChildren();batches.replaceChildren();company.replaceChildren();});
  document.getElementById('documentNewBatch').addEventListener('click',()=>{if(busy)return;batch=null;batches.value='';resetViewer();list.replaceChildren();setBusy(false);status.textContent='New batch · select files and upload.';});
  batches.addEventListener('change',async()=>{if(busy)return;batch=batches.value||null;resetViewer();list.replaceChildren();
    const option=batches.selectedOptions[0];if(option?.dataset.company)company.value=option.dataset.company;const id=generation;setBusy(true);
    try{await refresh();}catch(error){if(valid(id))status.textContent=error.message;}finally{if(valid(id))setBusy(false);}});
  document.getElementById('documentUpload').addEventListener('click',async()=>{
    if(busy||!company.value)return;const selected=Array.from(files.files||[]);
    if(!selected.length){status.textContent='Pehle files select karein.';return;}
    if(selected.length>50){status.textContent='Ek batch mein maximum 50 files select karein.';return;}
    const id=generation;setBusy(true);let uploaded=0,duplicates=0;const errors=[];
    try{
      if(!batch){const created=await api('/document-batches',json({company_id:company.value}));if(!valid(id))return;batch=created.id;}
      for(const file of selected){if(!valid(id))return;
        if(!file.size||file.size>10*1024*1024){errors.push(file.name+': 10 MB limit / empty file');continue;}
        status.textContent='Uploading '+file.name+'...';const body=new FormData();body.append('file',file);
        try{const data=await api('/document-batches/'+batch+'/documents',{method:'POST',body});uploaded++;if(data.duplicate)duplicates++;}
        catch(error){errors.push(file.name+': '+error.message);}
      }
      if(!valid(id))return;files.value='';await loadBatches(id,false);await refresh();
      if(valid(id))status.textContent=(uploaded-duplicates)+' new files · '+duplicates+' already saved'+(errors.length?' · '+errors.join(' | '):'');
    }catch(error){if(valid(id))status.textContent=error.message;}finally{if(valid(id))setBusy(false);}
  });
  document.getElementById('documentPrevious').addEventListener('click',()=>{if(current&&page>1)preview(current,page-1);});
  document.getElementById('documentNext').addEventListener('click',()=>{if(current&&page<current.page_count)preview(current,page+1);});
  document.getElementById('documentDownload').addEventListener('click',async()=>{if(!current)return;const id=generation,row=current;
    try{const blob=await (await request('/documents/'+row.id+'/original')).blob();if(!valid(id))return;
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=row.filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
    }catch(error){if(valid(id))status.textContent=error.message;}});
  document.getElementById('workspaceSelect')?.addEventListener('change',()=>{if(dialog.open)dialog.close();});
  document.getElementById('businessSignOut').addEventListener('click',()=>{if(dialog.open)dialog.close();});
  const authModal=document.getElementById('authModal');
  if(authModal)new MutationObserver(()=>{if(dialog.open&&scope!==scopeNow())dialog.close();}).observe(authModal,{attributes:true,attributeFilter:['class','style']});
})();
