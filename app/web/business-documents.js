// Private originals: authenticated fetch -> temporary blob; never public object URLs.
(() => {
  const dialog=document.getElementById('businessDocuments'),company=document.getElementById('documentCompany');
  const batches=document.getElementById('documentBatch'),files=document.getElementById('documentFiles');
  const list=document.getElementById('documentList'),status=document.getElementById('documentStatus');
  const viewer=document.getElementById('documentViewer'),pageLabel=document.getElementById('documentPage');
  const trashView=document.getElementById('documentTrashView');
  let scope=null,generation=0,batch=null,busy=false,poll=null,viewUrl=null,current=null,page=1,extractionTarget=null;
  let quick=false,selectedFiles=[];
  const autoExtract=new Set(),selectedList=document.getElementById('documentSelectedFiles');
  function renderSelected(){
    selectedList.replaceChildren();
    selectedFiles.forEach((file,index)=>{const row=document.createElement('div');row.className='document-selected-file';
      const name=document.createElement('span');name.textContent=file.name;
      const remove=document.createElement('button');remove.type='button';remove.textContent='Hatao';remove.disabled=busy;
      remove.setAttribute('aria-label','Remove '+file.name);remove.addEventListener('click',()=>{selectedFiles.splice(index,1);renderSelected();});
      row.append(name,remove);selectedList.append(row);});
    document.getElementById('documentUpload').disabled=busy||!company.value||(quick&&!selectedFiles.length)||trashView.value==='trash';
  }
  files.addEventListener('change',()=>{if(quick){selectedFiles=Array.from(files.files||[]);renderSelected();}});
  company.addEventListener('change',renderSelected);
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
  function resetViewer(){dialog.classList.remove('document-viewing');if(viewUrl)URL.revokeObjectURL(viewUrl);viewUrl=null;current=null;viewer.replaceChildren();pageLabel.textContent='';
    document.getElementById('documentPrevious').disabled=true;document.getElementById('documentNext').disabled=true;document.getElementById('documentDownload').disabled=true;}
  function setBusy(value){busy=value;trashView.disabled=value;files.disabled=value||trashView.value==='trash';document.getElementById('documentUpload').disabled=value||trashView.value==='trash';
    document.getElementById('documentNewBatch').disabled=value;batches.disabled=value;company.disabled=value||Boolean(batch);
    document.getElementById('documentManageBills').disabled=value;renderSelected();}
  async function preview(row,newPage=1){const id=generation;current=row;page=newPage;
    try{const path=row.media_type==='application/pdf'?'/documents/'+row.id+'/pages/'+newPage:'/documents/'+row.id+'/original';
      const blob=await (await request(path)).blob();if(!valid(id)||current?.id!==row.id||page!==newPage)return;
      if(viewUrl)URL.revokeObjectURL(viewUrl);viewUrl=URL.createObjectURL(blob);viewer.replaceChildren();
      const img=document.createElement('img');img.src=viewUrl;img.alt=row.filename+' · page '+newPage;viewer.append(img);
      dialog.classList.add('document-viewing');
      pageLabel.textContent=row.filename+' · '+newPage+' / '+row.page_count;
      document.getElementById('documentPrevious').disabled=newPage<=1;
      document.getElementById('documentNext').disabled=row.media_type!=='application/pdf'||newPage>=row.page_count;
      document.getElementById('documentDownload').disabled=false;
    }catch(error){if(valid(id))status.textContent=error.message;}
  }
  async function refresh(){const id=generation;if(!batch||!valid(id))return;
    const inTrash=trashView.value==='trash';
    const data=await api('/document-batches/'+batch+(inTrash?'?trashed=true':''));if(!valid(id)||data.id!==batch)return;
    let extractionStarted=false;
    for(const row of data.documents){
      if(quick&&autoExtract.has(row.id)&&row.status==='ready'){
        autoExtract.delete(row.id);
        if(!row.extraction_status||['not_started','pending'].includes(row.extraction_status)){
          try{await api('/documents/'+row.id+'/extract',json({}));extractionStarted=true;}
          catch(error){if(valid(id))status.textContent=error.message;}
          if(!valid(id))return;
        }
      }
    }
    if(extractionStarted){await refresh();return;}
    list.replaceChildren();
    if(!data.documents.length)list.textContent=inTrash?'Is batch ka Trash khali hai.':'Is batch mein abhi koi active file nahi hai.';
    for(const row of data.documents){const card=document.createElement('div');card.className='document-card';
      const name=document.createElement('strong');name.textContent=row.filename;
      const state=document.createElement('p');state.textContent=quick?(['queued','processing'].includes(row.extraction_status)?'Bill ki details check ho rahi hain…':row.extraction_status==='needs_review'?'Details ready · review karein':row.message):row.message+(row.page_count?' · '+row.page_count+' pages':'');card.append(name,state);
      if(row.status==='ready'&&!inTrash){
        const actions=document.createElement('div');actions.className='doc-card-actions';
        const open=document.createElement('button');open.type='button';open.textContent='View original';open.addEventListener('click',()=>preview(row));actions.append(open);
        const draftBtn=document.createElement('button');draftBtn.type='button';
        const extracting=['queued','processing'].includes(row.extraction_status);
        draftBtn.textContent=extracting?'Details check ho rahi hain…':row.extraction_status==='paused_budget'?'Budget paused · resume':row.extraction_status==='needs_review'?'Review bill':row.extraction_status==='error'?'Retry check':'Check bill';
        draftBtn.disabled=extracting;
        if(row.extraction_error){const error=document.createElement('p');error.textContent=row.extraction_error;card.append(error);}
        draftBtn.addEventListener('click',async()=>{
          if(busy)return;const stamp=generation;setBusy(true);
          try{
            const review=row.extraction_status==='needs_review';
            status.textContent=review?'Opening saved extracted draft...':'Extracting invoice details...';
            const ext=await api('/documents/'+row.id+(review?'/drafts':'/extract'),review?{}:json({}));
            if(!valid(stamp))return;
            const draftId=ext.draft?.id||ext.drafts?.[0]?.id;
            if(draftId){if(typeof window.openDraftWithDoc!=='function')throw new Error('Draft screen unavailable. Reload the app and open Bills · saved drafts.');dialog.close();await window.openDraftWithDoc(draftId);}
            else{extractionTarget=row.id;status.textContent='Extraction queued · processing will continue after reload. Open Review when ready.';await refresh();}
          }catch(error){if(valid(stamp))status.textContent=error.message;}
          finally{if(valid(stamp))setBusy(false);}
        });
        actions.append(draftBtn);card.append(actions);
      }
      if(row.retry_available&&!inTrash){const retry=document.createElement('button');retry.type='button';retry.textContent='Retry check';retry.addEventListener('click',async()=>{
        if(busy)return;const stamp=generation;setBusy(true);try{await api('/documents/'+row.id+'/retry',json({}));if(valid(stamp))await refresh();}
        catch(error){if(valid(stamp))status.textContent=error.message;}finally{if(valid(stamp))setBusy(false);}});card.append(retry);}
      const remove=document.createElement('button');remove.type='button';remove.textContent=inTrash?'Restore bill':'Move to Trash';
      remove.disabled=!inTrash&&(row.trash_available===false||['queued','processing'].includes(row.status)||['queued','processing'].includes(row.extraction_status));
      if(row.trash_reason&&!inTrash){const note=document.createElement('p');note.textContent=row.trash_reason;card.append(note);}
      let confirming=false;
      const cancel=document.createElement('button');cancel.type='button';cancel.textContent='Cancel';cancel.hidden=true;
      const confirmation=document.createElement('p');confirmation.hidden=true;
      confirmation.textContent='Original aur linked unposted drafts sab batches se Trash mein jayenge. Restore kar sakte hain; Tally entry delete nahi hogi.';
      cancel.addEventListener('click',()=>{confirming=false;remove.textContent='Move to Trash';cancel.hidden=true;confirmation.hidden=true;});
      remove.addEventListener('click',async()=>{
        if(busy)return;
        if(!inTrash&&!confirming){confirming=true;remove.textContent='Confirm move to Trash';cancel.hidden=false;confirmation.hidden=false;return;}
        const stamp=generation;setBusy(true);
        try{await api('/documents/'+row.id+(inTrash?'/restore':'/trash'),json({}));if(!valid(stamp))return;
          resetViewer();extractionTarget=null;await refresh();
          if(valid(stamp))status.textContent=inTrash?'Bill restored · Active bills mein dekhein.':'Bill Trash mein move hua · Show → Trash se Restore kar sakte hain.';
        }catch(error){if(valid(stamp))status.textContent=error.message;}
        finally{if(valid(stamp))setBusy(false);}
      });if(!quick){card.append(confirmation,remove);if(!inTrash)card.append(cancel);}list.append(card);
    }
    const extractingDocument=data.documents.find(row=>row.id===extractionTarget);
    if(extractingDocument&&status.textContent.startsWith('Extraction queued')){
      if(extractingDocument.extraction_status==='needs_review')status.textContent='Extraction complete · open Review extracted draft.';
      else if(['error','paused_budget'].includes(extractingDocument.extraction_status))status.textContent=extractingDocument.extraction_error||'Extraction needs attention. Check this document.';
    }
    clearTimeout(poll);poll=null;
    if(!inTrash&&data.documents.some(row=>['queued','processing'].includes(row.status)||['queued','processing'].includes(row.extraction_status)))poll=setTimeout(async()=>{
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
  async function open(){const id=++generation;scope=scopeNow();batch=null;trashView.value='active';extractionTarget=null;autoExtract.clear();selectedFiles=[];files.value='';resetViewer();list.replaceChildren();company.replaceChildren();setBusy(true);
    status.textContent=quick?'Files chunein, phir Upload aur check karo dabayein.':'PDF/JPG/PNG · 10 MB per file · 20 PDF pages · 50 files per batch';
    try{const data=await api('/purchase-drafts/companies');if(!valid(id))return;
      if(quick&&data.companies.length>1){const blank=document.createElement('option');blank.value='';blank.textContent='Company chunein';company.append(blank);}
      for(const row of data.companies){const option=document.createElement('option');option.value=row.id;option.textContent=row.name;company.append(option);}
      if(!data.companies.length)status.textContent='Pehle Tally setup mein company select karein.';
      if(!quick)await loadBatches(id);
    }catch(error){if(valid(id))status.textContent=error.message;}finally{if(valid(id))setBusy(false);}
  }
  function showDocuments(simple=false){
    if(dialog.open)return;
    quick=simple;dialog.classList.toggle('document-quick',quick);
    document.getElementById('documentHeading').textContent=quick?'Bill upload karein':'Manage bills';
    document.getElementById('documentUpload').textContent=quick?'Upload aur check karo':'Upload files';
    dialog.showModal();open();
  }
  // Both entry points share company scope, private upload, polling and review.
  // Attaching a bill never submits the chat composer or posts a Tally action.
  document.getElementById('businessDocumentsBtn').addEventListener('click',()=>showDocuments(false));
  document.getElementById('businessAttachBill').addEventListener('click',()=>{if(!window.businessChatAttachments?.enabled)showDocuments(true);});
  document.getElementById('documentManageBills').addEventListener('click',()=>{dialog.close();showDocuments(false);});
  document.getElementById('businessCloseDocuments').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{if(dialog.open)return;busy=false;generation++;scope=null;batch=null;autoExtract.clear();selectedFiles=[];clearTimeout(poll);poll=null;resetViewer();files.value='';list.replaceChildren();batches.replaceChildren();company.replaceChildren();});
  document.getElementById('documentNewBatch').addEventListener('click',()=>{if(busy)return;batch=null;batches.value='';resetViewer();list.replaceChildren();setBusy(false);status.textContent='New batch · select files and upload.';});
  trashView.addEventListener('change',async()=>{if(busy)return;const id=generation;resetViewer();extractionTarget=null;setBusy(true);
    status.textContent=trashView.value==='trash'?'Trash · originals private aur recoverable hain.':'Active bills';
    try{await refresh();}catch(error){if(valid(id))status.textContent=error.message;}finally{if(valid(id))setBusy(false);}});
  batches.addEventListener('change',async()=>{if(busy)return;batch=batches.value||null;resetViewer();list.replaceChildren();
    const option=batches.selectedOptions[0];if(option?.dataset.company)company.value=option.dataset.company;const id=generation;setBusy(true);
    try{await refresh();}catch(error){if(valid(id))status.textContent=error.message;}finally{if(valid(id))setBusy(false);}});
  document.getElementById('documentUpload').addEventListener('click',async()=>{
    if(busy||!company.value)return;const selected=quick?[...selectedFiles]:Array.from(files.files||[]);
    if(!selected.length){status.textContent='Pehle files select karein.';return;}
    if(selected.length>50){status.textContent='Ek batch mein maximum 50 files select karein.';return;}
    const id=generation;setBusy(true);let uploaded=0,duplicates=0;const errors=[];
    try{
      if(!batch){const created=await api('/document-batches',json({company_id:company.value}));if(!valid(id))return;batch=created.id;}
      for(const file of selected){if(!valid(id))return;
        if(!file.size||file.size>10*1024*1024){errors.push(file.name+': 10 MB limit / empty file');continue;}
        status.textContent='Uploading '+file.name+'...';const body=new FormData();body.append('file',file);
        try{const data=await api('/document-batches/'+batch+'/documents',{method:'POST',body});uploaded++;if(data.duplicate)duplicates++;
          if(quick){autoExtract.add(data.id||data.document?.id);selectedFiles=selectedFiles.filter(value=>value!==file);}}
        catch(error){errors.push(file.name+': '+error.message);}
      }
      if(!valid(id))return;files.value='';if(!quick)await loadBatches(id,false);await refresh();
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
