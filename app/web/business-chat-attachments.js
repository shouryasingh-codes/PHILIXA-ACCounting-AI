// Binary intake stays in the existing private document APIs. Commands carry IDs only.
(() => {
  const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  async function api(path,options={}){
    const r=await window.fetchWithAuth('/api/v1/business'+path,options);
    const d=await r.json();if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:'Bill request failed. Retry karein.');return d;
  }
  const json=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let previewEpoch=0;const previews=new Set();
  window.closeChatBillPreviews=()=>{previewEpoch++;for(const dialog of [...previews])dialog.close();};
  window.createChatAttachments=(host,changed)=>{
    let files=[],enabled=false,locked=false,scope=null,batch=null,requestId=null,commandText=null,generation=0;
    const box=el('div');box.className='chat-attachment-composer';box.hidden=true;
    const label=el('label','Bills ki company '),company=el('select');label.append(company);
    const chips=el('div');chips.className='chat-attachment-chips';
    const picker=el('input');picker.type='file';picker.multiple=true;picker.accept='.pdf,.jpg,.jpeg,.png';picker.hidden=true;
    const notice=el('p');notice.className='business-hint';notice.setAttribute('role','status');
    box.append(label,chips,notice,picker);host.prepend(box);
    function clear(){generation++;for(const item of files)if(item.url)URL.revokeObjectURL(item.url);files=[];batch=null;requestId=null;commandText=null;render();}
    function render(){
      box.hidden=!files.length;company.disabled=locked||!!batch;chips.replaceChildren();
      for(const item of files){const chip=el('div');chip.className='chat-attachment-chip';
        if(item.url){const img=el('img');img.src=item.url;img.alt='';chip.append(img);}
        const name=el('span',item.file.name+' · '+Math.ceil(item.file.size/1024)+' KB'+(item.document?' · Uploaded':''));chip.append(name);
        const remove=el('button','×');remove.type='button';remove.disabled=locked||commandText!==null;remove.setAttribute('aria-label','Remove '+item.file.name);
        remove.onclick=()=>{if(item.url)URL.revokeObjectURL(item.url);files=files.filter(x=>x!==item);if(!files.length){batch=null;requestId=null;}render();};chip.append(remove);chips.append(chip);}
      changed();
    }
    picker.onchange=()=>{
      const selected=[...picker.files];picker.value='';
      if(files.length+selected.length>50){notice.textContent='Maximum 50 files.';return;}
      for(const file of selected){if(!/\.(pdf|jpe?g|png)$/i.test(file.name)||file.size>10*1024*1024||!file.size){notice.textContent='PDF/JPG/PNG, 10 MB tak ki file chunein.';continue;}
        if(files.some(x=>x.file.name===file.name&&x.file.size===file.size&&x.file.lastModified===file.lastModified))continue;
        files.push({file,url:/^image\/(png|jpeg)$/.test(file.type)?URL.createObjectURL(file):null});}
      render();
    };
    company.onchange=()=>{batch=null;requestId=null;for(const item of files)item.document=null;};
    return {
      get hasFiles(){return enabled&&files.length>0;},get enabled(){return enabled;},
      setEnabled(value){enabled=value;},clear,
      async pick(currentScope){if(!enabled||locked)return;if(commandText!==null)throw new Error('Pichhla send uncertain hai. Wahi Send retry karein ya chat reload karein.');if(scope!==currentScope){clear();company.replaceChildren();scope=currentScope;}
        if(!company.options.length){const marker=generation;const data=await api('/purchase-drafts/companies');if(scope!==currentScope||marker!==generation)return;
          if(data.companies.length!==1){const blank=el('option','Company chunein');blank.value='';company.append(blank);}
          for(const row of data.companies){const option=el('option',row.name);option.value=row.id;company.append(option);}}
        picker.click();},
      lock(value){if(locked===value)return;locked=value;render();},
      async stage(text,currentScope){
        const marker=generation;const check=()=>{if(marker!==generation||scope!==currentScope)throw new Error('Workspace changed. Files dobara chunein.');};check();
        if(!company.value)throw new Error('Bills ki company chunein.');
        if(commandText!==null&&commandText!==text)throw new Error('Pichhla send uncertain hai. Wahi message retry karein ya chat reload karein.');
        requestId=requestId||window.crypto.randomUUID();
        if(!batch){const created=await api('/document-batches',json({company_id:company.value}));check();batch=created.id;}
        for(let i=0;i<files.length;i++)if(!files[i].document){notice.textContent=`Uploading ${i+1}/${files.length}: ${files[i].file.name}`;
          const body=new FormData();body.append('file',files[i].file);
          const result=await api('/document-batches/'+batch+'/documents',{method:'POST',body});check();files[i].document=result.document;render();}
        notice.textContent='Files uploaded. Chat mein save ho rahi hain…';commandText=text;
        return {request_id:requestId,attachments:[...new Set(files.map(item=>item.document.id))].map(document_id=>({document_id})),fields:{company_id:company.value}};
      }
    };
  };
  window.renderChatBillSources=(host,data)=>{
    const sources=data.chat_attachments||data.attachment_sources||[];
    for(const source of sources){const card=el('div');card.className='chat-bill-card';card.append(el('strong',source.filename||'Bill'));
      if(source.status)card.append(el('p',source.error||(['queued','processing'].includes(source.extraction_status)?'Bill ki details check ho rahi hain…':source.message||source.extraction_status||source.status)));
      const original=el('button','View original');original.type='button';original.onclick=async()=>{
        original.disabled=true;const marker=previewEpoch;let url=null;try{
          const response=await window.fetchWithAuth('/api/v1/business/documents/'+encodeURIComponent(source.document_id)+'/original');
          if(!response.ok)throw new Error('Original unavailable.');const blob=await response.blob();if(marker!==previewEpoch)return;url=URL.createObjectURL(blob);
          const dialog=el('dialog');dialog.className='chat-bill-original';const close=el('button','Close');close.type='button';close.onclick=()=>dialog.close();
          const preview=el(blob.type==='application/pdf'?'iframe':'img');preview.src=url;preview.title=source.filename||'Original bill';preview.alt=source.filename||'Original bill';
          if(preview.tagName==='IFRAME')preview.setAttribute('sandbox','');dialog.append(close,preview);document.body.append(dialog);
          previews.add(dialog);dialog.addEventListener('close',()=>{previews.delete(dialog);URL.revokeObjectURL(url);dialog.remove();},{once:true});dialog.showModal();
        }catch(error){card.append(el('p',error.message));if(url)URL.revokeObjectURL(url);}finally{original.disabled=false;}};
      card.append(original);
      for(const draft of source.drafts||[]){const content=draft.content||{};
        card.append(el('p',draft.status==='verified'?'Pehle se Tally verified · existing draft':'Saved draft · review required'));
        const conflicts=draft.extraction_metadata?.chat_source_conflicts||[];if(conflicts.length)card.append(el('p','Original/draft se correction: '+[...new Set(conflicts.map(c=>c.field))].join(', ')+'. Review required.'));
        card.append(el('p',[content.party_name,content.invoice_number,content.invoice_total!=null?'Bill total ₹'+content.invoice_total:null].filter(Boolean).join(' · ')||'Details review required'));
        const review=el('button','Review bill');review.type='button';review.onclick=()=>window.openDraftWithDoc?.(draft.id);card.append(review);}
      host.append(card);
    }
  };
})();
