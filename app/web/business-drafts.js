// Durable bill working copies with Day 4 Side-by-Side OCR extraction review. Save/reopen never approves a voucher.
(() => {
  const dialog=document.getElementById('businessDrafts');
  const form=document.getElementById('billDraftForm');
  const list=document.getElementById('billDraftList');
  const message=document.getElementById('billDraftStatus');
  const audit=document.getElementById('billDraftAudit');
  const company=document.getElementById('billDraftCompany');
  const preview=document.getElementById('billDraftPreview');
  const layout=document.getElementById('billDraftsLayout');
  const docPanel=document.getElementById('billDraftDocPanel');
  const docViewer=document.getElementById('billDraftDocViewer');
  const docPage=document.getElementById('billDraftDocPage');
  const docPrev=document.getElementById('billDraftDocPrev');
  const docNext=document.getElementById('billDraftDocNext');
  const docDownload=document.getElementById('billDraftDocDownload');
  const reviewBanner=document.getElementById('billDraftExtractionReview');

  let selected=null, scope=null, generation=0, busy=false;
  let docViewUrl=null, currentDocId=null, docCurrentPage=1, docTotalPages=1, docMediaType='application/pdf', docFilename='';
  const keys=['party_name','entry_date','godown','invoice_number'];
  const taxKeys=['supplier_gstin','place_of_supply','invoice_discount','round_off','invoice_total'];
  const taxHeads=['CGST','SGST','IGST','UTGST'];
  const taxTreatment=form.elements.namedItem('tax_treatment');
  let taxProfileRevision=0,taxLedgerInputs={},expectedTaxInputs={},unsupportedTreatments=[];
  const lineKeys=['item_name','quantity','unit','rate','discount_amount','discount_percent','gst_rate','hsn','taxable_amount'];
  const lineHost=document.getElementById('billDraftLines'),totalOutput=document.getElementById('billDraftTotal');
  let lineRows=[];
  let itemMasters=[];

  async function loadMasters(companyId,id){
    const data=await api('/companies/'+companyId+'/masters');if(!valid(id))return;
    itemMasters=data?.items||[];
    const suppliers=document.getElementById('billDraftSuppliers'),items=document.getElementById('billDraftItems');
    suppliers.replaceChildren();items.replaceChildren();
    for(const text of data?.suppliers||[]){const option=document.createElement('option');option.value=text;suppliers.append(option);}
    for(const row of itemMasters){const option=document.createElement('option');option.value=row.name;items.append(option);}
  }

  const normalLines=content=>(content.lines||[content]).map(line=>Object.fromEntries(lineKeys.map(k=>[k,line[k]??null])));
  function contentNow(){
    const tax=taxTreatment?.value?{tax_treatment:taxTreatment.value,
      ...Object.fromEntries(taxKeys.map(k=>[k,form.elements.namedItem(k)?.value?.trim()||null])),
      expected_taxes:Object.fromEntries(taxHeads.filter(h=>expectedTaxInputs[h]?.value?.trim()).map(h=>[h,expectedTaxInputs[h].value.trim()])),unsupported_treatments:unsupportedTreatments}:{};
    return {...tax,...Object.fromEntries(keys.map(k=>[k,form.elements.namedItem(k)?.value?.trim()||null])),
      lines:lineRows.map(row=>Object.fromEntries(lineKeys.map(k=>[k,row.inputs[k].value.trim()||null])))};
  }

  function cents(q,r){
    if(!/^\d+(\.\d{1,6})?$/.test(q)||!/^\d+(\.\d{1,2})?$/.test(r))return null;
    const scaled=(text,places)=>{const [whole,fraction='']=text.split('.');return BigInt(whole+fraction.padEnd(places,'0'));};
    const amount=scaled(q,6)*scaled(r,2),divisor=1000000n;
    let rounded=amount/divisor;const rem=amount%divisor;
    if(rem>divisor/2n||(rem===divisor/2n&&rounded%2n!==0n))rounded++;
    return rounded;
  }

  const money=n=>(n/100n).toString()+'.'+(n%100n).toString().padStart(2,'0');
  function updateTotals(){
    let total=0n,complete=true;
    for(const row of lineRows){
      const amount=cents(row.inputs.quantity.value,row.inputs.rate.value);
      row.amount.textContent=amount===null?'Amount pending':'₹'+money(amount);
      if(amount===null)complete=false;else total+=amount;
    }
    totalOutput.textContent=complete?(taxTreatment?.value?'Gross before discounts/GST: ₹'+money(total):'Total: ₹'+money(total)+' (non-GST)'):'Total pending · complete quantity/rate on each line';
  }

  function renderLines(lines, lineEvidence=[]){
    lineRows=[];lineHost.replaceChildren();
    for(const [index,line] of lines.entries()){
      const box=document.createElement('fieldset'),legend=document.createElement('legend');
      legend.textContent='Item '+(index+1);box.append(legend);
      const inputs={},taxLabels=[];
      const ev = lineEvidence[index] || null;

      for(const key of lineKeys){
        const label=document.createElement('label'),input=document.createElement('input');
        label.textContent={item_name:'Item name',quantity:'Quantity',unit:'Base unit',rate:'Rate ₹ (before tax)',discount_amount:'Line discount ₹',discount_percent:'Line discount %',gst_rate:'GST rate %',hsn:'HSN',taxable_amount:'Taxable amount from original ₹'}[key];
        input.value=line[key]??'';input.type=['item_name','unit','hsn'].includes(key)?'text':'number';
        if(key==='item_name')input.setAttribute('list','billDraftItems');
        input.maxLength=key==='unit'?50:200;
        if(input.type==='number'){input.min=key==='quantity'?'0.000001':key==='rate'?'0.01':'0';input.step=key==='quantity'?'0.000001':'0.01';}
        
        // Unclear or missing highlighting
        if(ev && (ev.unclear || (ev[key] && ev[key].confidence < 0.70) || (!line[key] && ['item_name','quantity','rate'].includes(key)))){
          input.classList?.add?.('input-unclear');
        }
        input.addEventListener('input',()=>{
          input.classList?.remove?.('input-unclear');
          updateTotals();
        });

        if(!['item_name','quantity','unit','rate'].includes(key)){label.hidden=!taxTreatment?.value;taxLabels.push(label);}
        label.append(input);box.append(label);inputs[key]=input;
      }

      inputs.item_name.addEventListener('change',()=>{
        const exact=itemMasters.filter(item=>item.name===inputs.item_name.value);
        if(exact.length===1&&!inputs.unit.value){inputs.unit.value=exact[0].unit;updateTotals();}
      });

      if(ev && ev.warnings && ev.warnings.length){
        const wSpan=document.createElement('span');wSpan.className='line-warning-badge';
        wSpan.textContent='⚠️ '+ev.warnings.join(' · ');
        box.append(wSpan);
      }

      const amount=document.createElement('output'),remove=document.createElement('button');
      remove.type='button';remove.textContent='Remove item '+(index+1);
      remove.addEventListener('click',()=>{
        if(busy||selected&&!selected.editable||lineRows.length===1)return;
        const values=contentNow().lines;values.splice(index,1);
        renderLines(values);setBusy(false);
      });
      box.append(amount,remove);lineHost.append(box);lineRows.push({inputs,amount,remove,taxLabels});
    }
    updateTotals();
  }

  const scopeNow=()=>JSON.stringify(window.getBusinessChatScope?.()||null);
  const setBusy=value=>{
    busy=value;form.querySelectorAll('button').forEach(b=>b.disabled=value);
    for(const key of [...keys,...taxKeys,'tax_treatment']){const el=form.elements.namedItem(key);if(el)el.disabled=value||Boolean(selected&&!selected.editable);}
    for(const row of lineRows){
      for(const input of Object.values(row.inputs))input.disabled=value||Boolean(selected&&!selected.editable);
      row.remove.disabled=value||Boolean(selected&&!selected.editable)||lineRows.length===1;
    }
    document.getElementById('billDraftAddLine').disabled=value||Boolean(selected&&!selected.editable)||lineRows.length>=100;
    for(const input of Object.values({...expectedTaxInputs,...taxLedgerInputs})){input.disabled=value||Boolean(selected&&!selected.editable);}
    company.disabled=value||Boolean(selected);
    document.getElementById('billDraftMakePreview').disabled=value||!selected;
  };

  async function api(path='',options={}) {
    if(scope!==scopeNow())throw new Error('Workspace/session changed. Reopen Bills.');
    const response=await window.fetchWithAuth('/api/v1/business/purchase-drafts'+path,options);
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Bill draft request failed.');
    return data;
  }

  const json=(body,method)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

  function resetDocPanel(){
    if(typeof URL!=='undefined'&&docViewUrl)URL.revokeObjectURL(docViewUrl);
    docViewUrl=null;currentDocId=null;docCurrentPage=1;docTotalPages=1;
    if(docViewer)docViewer.replaceChildren();
    if(docPage)docPage.textContent='';
    if(docPanel)docPanel.hidden=true;
    layout?.classList?.remove?.('has-doc');
    dialog?.classList?.remove?.('side-by-side');
  }

  async function loadDocPage(docId, newPage=1){
    const stamp=generation;
    currentDocId=docId;docCurrentPage=newPage;
    try{
      const path=docMediaType==='application/pdf'?'/documents/'+docId+'/pages/'+newPage:'/documents/'+docId+'/original';
      const response=await window.fetchWithAuth('/api/v1/business'+path);
      if(!response.ok)throw new Error('Source page load failed');
      const blob=await response.blob();
      if(!valid(stamp)||currentDocId!==docId||docCurrentPage!==newPage)return;
      if(typeof URL!=='undefined'&&docViewUrl)URL.revokeObjectURL(docViewUrl);
      docViewUrl=typeof URL!=='undefined'?URL.createObjectURL(blob):'';
      docViewer.replaceChildren();
      const img=document.createElement('img');img.src=docViewUrl;img.alt=(docFilename||'Source bill')+' · page '+newPage;
      docViewer.append(img);
      docPage.textContent=(docFilename||'Source Document')+' · Page '+newPage+' / '+docTotalPages;
      docPrev.disabled=newPage<=1;
      docNext.disabled=docMediaType!=='application/pdf'||newPage>=docTotalPages;
      docDownload.disabled=false;
    }catch(err){
      if(valid(stamp)&&docPage)docPage.textContent=err.message;
    }
  }

  async function setupSideBySide(row){
    if(!row.document_id){
      resetDocPanel();return;
    }
    const docId=row.document_id,stamp=generation;
    try{
      const response=await window.fetchWithAuth('/api/v1/business/documents/'+docId);
      if(!response.ok){if(valid(stamp))resetDocPanel();return;}
      const docData=await response.json();
      if(!valid(stamp)||selected?.id!==row.id)return;
      docTotalPages=docData.page_count||1;
      docMediaType=docData.media_type||'application/pdf';
      docFilename=docData.filename||'Invoice';
      if(docPanel)docPanel.hidden=false;
      layout?.classList?.add?.('has-doc');
      dialog?.classList?.add?.('side-by-side');
      await loadDocPage(docId, 1);
    }catch(err){
      if(valid(stamp)){console.warn('Doc viewer setup error:', err);resetDocPanel();}
    }
  }

  function renderExtractionBanner(row){
    reviewBanner.replaceChildren();
    const meta=row.extraction_metadata;
    if(!meta){
      reviewBanner.hidden=true;return;
    }
    reviewBanner.hidden=false;
    const clean=!(meta.warnings&&meta.warnings.length);
    reviewBanner.className='extraction-review-card'+(clean?' clean':'');

    const badgeRow=document.createElement('div');badgeRow.className='review-badge-row';
    const confScore=Math.round((meta.confidence?.overall ?? 0) * 100);
    const confBadge=document.createElement('span');confBadge.className='badge-confidence';
    confBadge.textContent=confScore?'✧ Extracted · '+confScore+'% model confidence (review required)':'✧ Extracted · confidence unavailable';

    const statusBadge=document.createElement('span');statusBadge.className='badge-review';
    statusBadge.textContent='Status: '+(row.status==='needs_review'?'Review required':'Draft');
    badgeRow.append(confBadge, statusBadge);

    if(row.document_filename){
      const srcBadge=document.createElement('span');srcBadge.className='review-evidence-summary';
      srcBadge.textContent='Source: '+row.document_filename+(meta.source_pages?' (Pages '+meta.source_pages.join(', ')+')':'');
      badgeRow.append(srcBadge);
    }
    reviewBanner.append(badgeRow);

    if(meta.warnings && meta.warnings.length){
      const warnList=document.createElement('ul');warnList.className='review-warnings-list';
      for(const w of meta.warnings){
        const li=document.createElement('li');li.textContent='⚠️ '+w;warnList.append(li);
      }
      reviewBanner.append(warnList);
    }

    if(meta.multiple_invoices_detected&&!meta.is_split_draft){
      const splitBtn=document.createElement('button');splitBtn.type='button';splitBtn.className='btn-split';
      splitBtn.textContent='Split into separate invoice drafts';
      splitBtn.addEventListener('click', async()=>{
        if(busy||!row.document_id)return;
        const stamp=generation;setBusy(true);
        try{
          message.textContent='Splitting invoice document into multiple drafts…';
          const response=await window.fetchWithAuth('/api/v1/business/documents/'+row.document_id+'/split',json({},'POST'));
          let splitRes=await response.json();
          if(!response.ok)throw new Error(splitRes.detail||'Split failed.');
          while(!splitRes.drafts?.length&&['queued','processing'].includes(splitRes.status)){
            await new Promise(resolve=>setTimeout(resolve,3000));if(!valid(stamp))return;
            const stateResponse=await window.fetchWithAuth('/api/v1/business/documents/'+row.document_id);
            if(!stateResponse.ok)throw new Error('Split status unavailable. Reopen Bills.');
            const state=await stateResponse.json();
            if(state.extraction_status==='error')throw new Error(state.extraction_error||'Split failed.');
            if(state.extraction_status==='needs_review'){
              const listingResponse=await window.fetchWithAuth('/api/v1/business/documents/'+row.document_id+'/drafts');
              if(!listingResponse.ok)throw new Error('Drafts unavailable.');
              const listed=await listingResponse.json();splitRes={drafts:listed.drafts.filter(d=>d.extraction_metadata?.is_split_draft)};
            }
          }
          if(!valid(stamp))return;
          const draftsList=splitRes.drafts || (splitRes.draft ? [splitRes.draft] : []);
          message.textContent='Document split into '+draftsList.length+' drafts.';
          await listing(stamp);
          if(draftsList.length){
            const first=draftsList[0];
            const current=await api('/'+first.id);
            const events=await api('/'+first.id+'/audit');
            show(current);showAudit(events.events);
            await setupSideBySide(current);if(current.content.tax_treatment)await loadTaxSetup(current.company_id,stamp);
            message.textContent='Document split into '+draftsList.length+' drafts · '+current.id+' (Revision '+current.revision+').';
          }
        }catch(e){if(valid(stamp))message.textContent=e.message;}
        finally{if(stamp===generation)setBusy(false);}
      });
      reviewBanner.append(splitBtn);
    }
  }

  function clear() {
    selected=null;form.reset();audit.replaceChildren();preview.replaceChildren();
    unsupportedTreatments=[];for(const input of Object.values(expectedTaxInputs))input.value='';
    const taxFields=document.getElementById('billDraftTaxFields');if(taxFields)taxFields.hidden=true;
    const result=document.getElementById('billDraftTaxResult');if(result)result.textContent='';
    resetDocPanel();
    reviewBanner.hidden=true;reviewBanner.replaceChildren();
    renderLines([{}]);
    company.disabled=false;
    keys.forEach(key=>{const el=form.elements.namedItem(key);if(el)el.disabled=false;});
    document.getElementById('billDraftSave').hidden=false;
    document.getElementById('billDraftMakePreview').hidden=false;
    message.textContent='Draft save karne se Tally entry post nahi hogi.';
    setBusy(false);
  }

  function show(row) {
    selected=row;company.value=row.company_id;company.disabled=true;
    for(const key of [...keys,...taxKeys,'tax_treatment']){
      const input=form.elements.namedItem(key);
      if(input){input.value=row.content[key]??'';input.disabled=!row.editable;
        const evidence=row.extraction_metadata?.field_evidence?.[key];
        input.classList?.toggle?.('input-unclear',Boolean(evidence&&(evidence.confidence??0)<0.8));
      }
    }
    unsupportedTreatments=row.content.unsupported_treatments||[];
    for(const h of taxHeads){if(expectedTaxInputs[h])expectedTaxInputs[h].value=row.content.expected_taxes?.[h]??'';}
    const taxFields=document.getElementById('billDraftTaxFields');if(taxFields)taxFields.hidden=!row.content.tax_treatment;
    renderLines(normalLines(row.content), row.extraction_metadata?.line_evidence || []);
    renderExtractionBanner(row);
    document.getElementById('billDraftSave').hidden=!row.editable;
    document.getElementById('billDraftMakePreview').hidden=!row.editable;
    message.textContent='Revision '+row.revision+' · '+row.status;
  }

  function showAudit(events) {
    audit.replaceChildren();
    for(const event of events){
      const line=document.createElement('p');
      line.textContent='Revision '+event.revision+' · '+event.kind+' · '+new Date(event.created_at).toLocaleString();
      audit.append(line);
    }
  }

  function valid(id){return id===generation&&scope===scopeNow()&&dialog.open;}

  async function listing(id) {
    const data=await api();if(!valid(id))return;
    list.replaceChildren();
    if(!data.drafts.length){list.textContent='Abhi koi saved bill draft nahi hai.';return;}
    for(const row of data.drafts){
      const button=document.createElement('button');button.type='button';
      const lines=normalLines(row.content),itemLabel=(lines[0]?.item_name||'Item pending')+(lines.length>1?' + '+(lines.length-1)+' items':'');
      const invTag=row.content.invoice_number ? ' ['+row.content.invoice_number+']' : '';
      const docTag=row.document_id ? ' 📄' : '';
      button.textContent=(row.content.party_name||'Incomplete purchase')+invTag+' · '+itemLabel+docTag+' · '+row.status;
      button.addEventListener('click',async()=>{
        if(busy)return;setBusy(true);const stamp=generation;
        try{
          const current=await api('/'+row.id);
          const events=await api('/'+row.id+'/audit');
          await loadMasters(current.company_id,stamp);
          if(!valid(stamp))return;
          preview.replaceChildren();show(current);showAudit(events.events);
          await setupSideBySide(current);if(current.content.tax_treatment)await loadTaxSetup(current.company_id,stamp);
        }catch(error){if(valid(stamp))message.textContent=error.message;}
        finally{if(stamp===generation)setBusy(false);}
      });
      list.append(button);
    }
  }

  async function load() {
    const id=++generation;scope=scopeNow();clear();list.replaceChildren();company.replaceChildren();setBusy(true);
    try{
      const data=await api('/companies');if(!valid(id))return;
      for(const row of data.companies){const option=document.createElement('option');option.value=row.id;option.textContent=row.name;company.append(option);}
      if(data.companies.length)await loadMasters(data.companies[0].id,id);
      if(!data.companies.length)message.textContent='Pehle Tally setup mein company select karein.';
      await listing(id);
    }catch(error){if(valid(id))message.textContent=error.message;}
    finally{if(id===generation)setBusy(false);}
  }

  // Public helper to open a specific draft with side-by-side view
  window.openDraftWithDoc=async function(draftId){
    dialog.showModal();
    const id=++generation;scope=scopeNow();clear();list.replaceChildren();company.replaceChildren();setBusy(true);
    try{
      const data=await api('/companies');if(!valid(id))return;
      for(const row of data.companies){const option=document.createElement('option');option.value=row.id;option.textContent=row.name;company.append(option);}
      const current=await api('/'+draftId);
      if(current.company_id)await loadMasters(current.company_id,id);
      if(!valid(id))return;
      preview.replaceChildren();show(current);
      const events=await api('/'+draftId+'/audit');
      showAudit(events.events);
      await setupSideBySide(current);if(current.content.tax_treatment)await loadTaxSetup(current.company_id,id);
      await listing(id);
    }catch(e){if(valid(id))message.textContent=e.message;}
    finally{if(id===generation)setBusy(false);}
  };

  document.getElementById('businessDraftsBtn').addEventListener('click',()=>{dialog.showModal();load();});
  document.getElementById('businessCloseDrafts').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{
    generation++;scope=null;busy=false;clear();list.replaceChildren();company.replaceChildren();itemMasters=[];
    resetDocPanel();
    document.getElementById('billDraftItems').replaceChildren();document.getElementById('billDraftSuppliers').replaceChildren();
  });

  docPrev.addEventListener('click',()=>{if(currentDocId&&docCurrentPage>1)loadDocPage(currentDocId,docCurrentPage-1);});
  docNext.addEventListener('click',()=>{if(currentDocId&&docCurrentPage<docTotalPages)loadDocPage(currentDocId,docCurrentPage+1);});
  docDownload.addEventListener('click',async()=>{
    if(!currentDocId)return;
    try{
      const response=await window.fetchWithAuth('/api/v1/business/documents/'+currentDocId+'/original');
      const blob=await response.blob();
      const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=docFilename||'bill-original';
      link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
    }catch(err){message.textContent=err.message;}
  });

  async function loadTaxSetup(companyId,id){
    const data=await api('/companies/'+companyId+'/tax-profile');if(!valid(id))return;
    if(data.gst_enabled===false)message.textContent='Selected company has GST disabled or GST masters need sync. Use a separate GST test company for tax previews.';
    taxProfileRevision=data.revision;const host=document.getElementById('billDraftTaxLedgers');if(!host)return;
    host.replaceChildren();taxLedgerInputs={};
    for(const head of taxHeads){const label=document.createElement('label'),select=document.createElement('select');label.textContent=head+' ledger';
      const empty=document.createElement('option');empty.value='';empty.textContent='Select existing ledger';select.append(empty);
      for(const name of data.candidates[head]||[]){const option=document.createElement('option');option.value=name;option.textContent=name;select.append(option);}
      select.value=data.profile.ledgers[head]||'';label.append(select);host.append(label);taxLedgerInputs[head]=select;
    }
    document.getElementById('billDraftRoundingLedger').value=data.profile.rounding_ledger||'';
    const choices=document.getElementById('billDraftRoundingChoices');choices.replaceChildren();
    for(const name of data.rounding_candidates||[]){const option=document.createElement('option');option.value=name;choices.append(option);}
  }
  const taxHost=document.getElementById('billDraftExpectedTaxes');
  if(taxHost){for(const head of taxHeads){const label=document.createElement('label'),input=document.createElement('input');
    label.textContent=head+' amount from original ₹';input.type='number';input.min='0';input.step='0.01';label.append(input);taxHost.append(label);expectedTaxInputs[head]=input;}}
  taxTreatment?.addEventListener('change',async()=>{
    document.getElementById('billDraftTaxFields').hidden=!taxTreatment.value;
    for(const row of lineRows)for(const label of row.taxLabels)label.hidden=!taxTreatment.value;updateTotals();
    if(taxTreatment.value&&company.value){const stamp=generation;setBusy(true);try{await loadTaxSetup(company.value,stamp);}catch(e){if(valid(stamp))message.textContent=e.message;}finally{if(valid(stamp))setBusy(false);}}
  });
  document.getElementById('billDraftSaveTaxProfile')?.addEventListener('click',async()=>{
    if(busy||!company.value)return;const stamp=generation;setBusy(true);
    try{const data=await api('/companies/'+company.value+'/tax-profile',json({revision:taxProfileRevision,
      ledgers:Object.fromEntries(taxHeads.filter(h=>taxLedgerInputs[h]?.value).map(h=>[h,taxLedgerInputs[h].value])),
      rounding_ledger:document.getElementById('billDraftRoundingLedger').value.trim()||null},'PUT'));
      if(valid(stamp)){taxProfileRevision=data.revision;message.textContent='Company GST setup saved. Review a fresh preview after changes.';}
    }catch(e){if(valid(stamp))message.textContent=e.message;}finally{if(valid(stamp))setBusy(false);}
  });
  document.getElementById('billDraftTaxCheck')?.addEventListener('click',async()=>{
    if(busy||!selected)return;const stamp=generation;setBusy(true);
    try{const data=await api('/'+selected.id+'/tax-check');if(!valid(stamp))return;
      document.getElementById('billDraftTaxResult').textContent='Saved revision '+selected.revision+': taxable ₹'+data.taxable_total+' · '+data.tax_ledgers.map(r=>r.head+' ₹'+r.amount).join(' · ')+' · round-off ₹'+data.round_off+' · total ₹'+data.total;
    }catch(e){if(valid(stamp))message.textContent=e.message;}finally{if(valid(stamp))setBusy(false);}
  });
  company.addEventListener('change',async()=>{
    if(busy)return;const id=generation;setBusy(true);
    try{await loadMasters(company.value,id);}catch(error){if(valid(id))message.textContent=error.message;}finally{if(id===generation)setBusy(false);}
  });

  document.getElementById('billDraftNew').addEventListener('click',()=>{if(!busy)clear();});
  document.getElementById('billDraftReload').addEventListener('click',()=>{if(!busy)load();});
  document.getElementById('billDraftAddLine').addEventListener('click',()=>{
    if(busy||selected&&!selected.editable||lineRows.length>=100)return;
    renderLines([...contentNow().lines,{}]);setBusy(false);
  });

  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!company.value)return;
    if(scope!==scopeNow()){dialog.close();return;}
    const content=contentNow();
    const id=generation;setBusy(true);
    try{
      const row=selected?await api('/'+selected.id,json({revision:selected.revision,content},'PUT')):
          await api('',json({company_id:company.value,content},'POST'));
      if(!valid(id))return;preview.replaceChildren();show(row);message.textContent='Draft saved · revision '+row.revision+'. Tally mein post nahi hua.';
      const events=await api('/'+row.id+'/audit');if(!valid(id))return;showAudit(events.events);
      await listing(id);
    }catch(error){if(valid(id))message.textContent=error.message;}
    finally{if(id===generation)setBusy(false);}
  });

  document.getElementById('billDraftMakePreview').addEventListener('click',async()=>{
    if(busy||!selected)return;
    if(scope!==scopeNow()){dialog.close();return;}
    const savedTax=selected.content.tax_treatment?{tax_treatment:selected.content.tax_treatment,...Object.fromEntries(taxKeys.map(k=>[k,selected.content[k]??null])),expected_taxes:selected.content.expected_taxes||{},unsupported_treatments:selected.content.unsupported_treatments||[]}:{};
    const saved={...savedTax,...Object.fromEntries(keys.map(k=>[k,selected.content[k]??null])),lines:normalLines(selected.content)};
    if(JSON.stringify(contentNow())!==JSON.stringify(saved)){message.textContent='Pehle edited draft save karein.';return;}
    const id=generation;setBusy(true);
    try{
      const data=await api('/'+selected.id+'/preview',json({revision:selected.revision},'POST'));
      if(!valid(id))return;preview.replaceChildren();message.textContent=data.response;
      for(const text of data.preview.lines){const line=document.createElement('p');line.textContent=text;preview.append(line);}
      if(data.preview.can_confirm===false){
        for(const blocker of data.preview.blockers||[]){const note=document.createElement('p');note.textContent=blocker;preview.append(note);}
        const refreshed=await api('/'+selected.id);if(valid(id))show(refreshed);return;
      }
      const confirm=document.createElement('button');confirm.type='button';confirm.textContent='Confirm & save to Tally';
      const currentScope=scope;
      confirm.addEventListener('click',async()=>{
        if(busy||currentScope!==scopeNow()||!valid(id))return;setBusy(true);confirm.disabled=true;
        try{
          const response=await window.fetchWithAuth('/api/v1/business/confirm',json({token:data.preview.token,approve:true},'POST'));
          const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Confirmation failed');
          if(!valid(id))return;const refreshed=await api('/'+selected.id);if(!valid(id))return;
          preview.replaceChildren();show(refreshed);message.textContent=result.response;await listing(id);
        }catch(error){if(valid(id))message.textContent=error.message;}
        finally{if(id===generation)setBusy(false);}
      });
      preview.append(confirm);
      const refreshed=await api('/'+selected.id);if(!valid(id))return;show(refreshed);
      const events=await api('/'+selected.id+'/audit');if(!valid(id))return;showAudit(events.events);await listing(id);
    }catch(error){if(valid(id))message.textContent=error.message;}
    finally{if(id===generation)setBusy(false);}
  });

  const workspace=document.getElementById('workspaceSelect');
  workspace?.addEventListener('change',()=>{if(dialog.open)dialog.close();});
  document.getElementById('businessSignOut').addEventListener('click',()=>{if(dialog.open)dialog.close();});
})();
