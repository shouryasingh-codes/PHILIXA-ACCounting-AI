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
  const receiptPanel=document.getElementById('billReceiptLink');
  let receiptChoices=[];
  receiptPanel?.addEventListener('toggle',async()=>{
    if(!receiptPanel.open||!selected||busy)return;
    const stamp=generation,draftId=selected.id;
    const choices=document.getElementById('billReceiptChoice'),status=document.getElementById('billReceiptLinkStatus');
    choices.replaceChildren();status.textContent='Verified receipts check ho rahi hain…';
    try{
      const data=await api('/companies/'+selected.company_id+'/receipts');
      if(!valid(stamp)||selected?.id!==draftId)return;
      receiptChoices=data.receipts.filter(r=>r.supplier===selected.content.party_name);
      for(const receipt of receiptChoices){const option=document.createElement('option');option.value=receipt.id;option.textContent=receipt.tracking+' · '+receipt.received_on;choices.append(option);}
      document.getElementById('billReceiptAttach').disabled=!receiptChoices.length;
      status.textContent=receiptChoices.length?'Original receipt aur bill ki quantities match honi chahiye.':'Is supplier ki unbilled verified Receipt Note nahi mili.';
    }catch(error){if(valid(stamp))status.textContent=error.message;}
  });
  document.getElementById('billReceiptAttach')?.addEventListener('click',async()=>{
    if(!selected||busy)return;
    const status=document.getElementById('billReceiptLinkStatus');
    if(form.dataset?.dirty==='true'){status.textContent='Pehle bill ki changes save karein.';return;}
    const receipt=receiptChoices.find(r=>r.id===document.getElementById('billReceiptChoice').value);
    if(!receipt)return;
    const stamp=generation,draftId=selected.id;setBusy(true);
    try{
      const result=await api('/'+draftId+'/receipt-link',json({revision:selected.revision,receipt_draft_id:receipt.id,receipt_revision:receipt.revision}));
      if(!valid(stamp)||selected?.id!==draftId)return;
      show(result);message.textContent='Receipt link saved. Ab validated Tally preview check karein; abhi invoice post nahi hua.';
    }catch(error){if(valid(stamp))status.textContent=error.message;}
    finally{if(stamp===generation)setBusy(false);}
  });
  document.getElementById('billDraftChat')?.addEventListener('click',()=>{
    if(busy||!selected||!selected.editable)return;
    if(form.dataset?.dirty==='true'){message.textContent='Pehle edited details Save karein; phir Continue in chat.';return;}
    if(typeof window.continuePurchaseChat!=='function'){message.textContent='Chat screen load nahi hui. Reload karein.';return;}
    const draftId=selected.id;dialog.close();window.continuePurchaseChat(draftId);
  });
  const reviewMeter=window.BillReviewMeter?new window.BillReviewMeter({
    active:()=>dialog.open&&!busy&&document.visibilityState==='visible'&&document.hasFocus(),
    send:async sample=>{
      if(sample.context.scope!==scopeNow())return;
      const response=await window.fetchWithAuth('/api/v1/business/purchase-drafts/'+sample.context.id+'/review-time',json(sample.body));
      if(!response.ok)throw new Error('Review timing not recorded');
    }
  }):null;
  for(const event of ['pointerdown','keydown','input'])dialog.addEventListener(event,()=>reviewMeter?.activity());
  if(reviewMeter&&typeof setInterval!=='undefined'){
    setInterval(()=>reviewMeter.tick(),2500);
    setInterval(()=>reviewMeter.flush().catch(()=>{}),10000);
    document.addEventListener('visibilitychange',()=>reviewMeter.flush().catch(()=>{}));
    window.addEventListener('pagehide',()=>reviewMeter.flush().catch(()=>{}));
  }
  document.getElementById('billEvaluationMetrics')?.addEventListener('click',async()=>{
    if(!selected||busy)return;const id=selected.id,stamp=generation;
    try{await reviewMeter?.flush();const result=await api('/'+id+'/evaluation-metrics');if(!valid(stamp)||selected?.id!==id)return;
      message.textContent='Corrections: '+result.correction_count+' fields · Active review: '+(result.active_review_ms==null?'unmeasured':(result.active_review_ms/1000).toFixed(1)+'s (estimate)')+' · Processing: '+(result.processing_latency_ms==null?'unmeasured':result.processing_latency_ms+'ms')+' · Provider cost: '+(result.provider_cost_usd==null?'unknown':'$'+result.provider_cost_usd)+' · Real-world accuracy unverified.';
    }catch(e){if(valid(stamp))message.textContent=e.message;}
  });
  let automationScope=null,automationRevision=0,decisionRequest=0,automationPausing=false;
  const autoEl=id=>document.getElementById('billAutomation'+id);
  function resetAutomation(){
    automationScope=null;automationRevision=0;decisionRequest++;
    if(autoEl('Save'))autoEl('Save').disabled=true;
    if(autoEl('Status'))autoEl('Status').textContent='Load the selected company policy before editing.';
    autoEl('Decisions')?.replaceChildren();
  }
  function renderDecisions(rows){
    const host=autoEl('Decisions');if(!host)return;host.replaceChildren();
    for(const row of rows||[]){const p=document.createElement('p');p.textContent=row.decision+' · bill revision '+row.revision+' · policy '+row.policy_revision+' · '+row.reasons.join(' ');host.append(p);}
  }
  autoEl('Load')?.addEventListener('click',async()=>{
    if(busy||!company.value)return;const stamp=generation,cid=company.value;setBusy(true);
    try{const result=await api('/companies/'+cid+'/automation');if(!valid(stamp)||company.value!==cid)return;
      automationScope=cid;automationRevision=result.revision;
      autoEl('Mode').value=result.policy.mode;
      for(const [id,key] of [['Suppliers','suppliers'],['Items','items']])autoEl(id).value=(result.policy[key]||[]).join('\n');
      for(const [id,key] of [['Invoice','per_invoice'],['Amount','daily_amount'],['Count','daily_count']])autoEl(id).value=result.policy[key]??'';
      autoEl('Save').disabled=false;autoEl('Status').textContent='Policy '+result.revision+' · '+(result.enabled?result.policy.mode:'disabled')+' · Today '+result.usage.count+' bills / ₹'+result.usage.amount+' (India time).';
    }catch(e){autoEl('Status').textContent=e.message;}finally{if(stamp===generation)setBusy(false);}
  });
  autoEl('Save')?.addEventListener('click',async()=>{
    if(busy||automationScope!==company.value)return;const stamp=generation,cid=company.value;setBusy(true);
    try{const body={revision:automationRevision,mode:autoEl('Mode').value,
      suppliers:autoEl('Suppliers').value.split('\n').map(v=>v.trim()).filter(Boolean),items:autoEl('Items').value.split('\n').map(v=>v.trim()).filter(Boolean),
      per_invoice:autoEl('Invoice').value||null,daily_amount:autoEl('Amount').value||null,daily_count:autoEl('Count').value?Number(autoEl('Count').value):null};
      const result=await api('/companies/'+cid+'/automation',json(body,'PUT'));if(!valid(stamp)||company.value!==cid)return;
      automationRevision=result.revision;autoEl('Status').textContent='Policy saved · '+(result.enabled?result.policy.mode:'disabled')+'. Auto mode processes eligible saved bills. Pause prevents further dispatch.';
    }catch(e){if(valid(stamp))autoEl('Status').textContent=e.message;}finally{if(stamp===generation)setBusy(false);}
  });
  autoEl('Pause')?.addEventListener('click',async()=>{
    // Pause remains available while an evaluation is waiting on connector reads.
    if(automationPausing||!company.value)return;const stamp=generation,cid=company.value;automationPausing=true;autoEl('Pause').disabled=true;
    try{const result=await api('/companies/'+cid+'/automation/pause',json({}));if(!valid(stamp)||company.value!==cid)return;
      automationScope=null;autoEl('Save').disabled=true;autoEl('Mode').value='paused';
      autoEl('Status').textContent='Paused · policy '+result.revision+'. Unsent automatic entries will stop. Already dispatched entries are reconciled.';
    }catch(e){if(valid(stamp))autoEl('Status').textContent=e.message;}finally{automationPausing=false;autoEl('Pause').disabled=false;}
  });
  autoEl('Evaluate')?.addEventListener('click',async()=>{
    if(busy||!selected)return;
    if(form.dataset?.dirty==='true'){autoEl('Status').textContent='Save bill changes before evaluation.';return;}
    const stamp=generation,draftId=selected.id;setBusy(true);
    try{const result=await api('/'+draftId+'/automation-evaluate',json({}));if(!valid(stamp)||selected?.id!==draftId)return;
      const row=await api('/'+draftId);if(!valid(stamp)||selected?.id!==draftId)return;show(row);decisionRequest++;renderDecisions([result]);await listing(stamp);
    }catch(e){if(valid(stamp))autoEl('Status').textContent=e.message;}finally{if(stamp===generation)setBusy(false);}
  });
  let queueRows=[],queueOffset=0,queueView='all',queueSelection=new Map(),queueButtons=[],queueGeneration=0,queueLoading=false;
  const queueApprove=document.getElementById('billQueueApprove');
  function selectionState(){
    if(queueApprove){queueApprove.disabled=busy||queueLoading||!queueSelection.size;queueApprove.textContent='Approve selected ('+queueSelection.size+')';}
  }

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
  let chatSimple=false,chatStep=1;
  const chatSteps=document.getElementById('billChatSteps');
  function paintChatSteps(){
    if(!chatSteps)return;
    chatSteps.hidden=!chatSimple;
    if(dialog.dataset){dialog.dataset.chatSimple=chatSimple?'true':'false';dialog.dataset.chatStep=String(chatStep);}
    if(!chatSimple)return;
    const get=id=>document.getElementById(id);
    get('billChatStepTitle').textContent=chatStep===1?'1 / 2 · Purchase details':'2 / 2 · Invoice & GST check';
    get('billChatStepSummary').textContent=lineRows.map(r=>[r.inputs.item_name.value,r.inputs.quantity.value,r.inputs.unit.value].filter(Boolean).join(' · ')).join(' | ');
    get('billChatStepHint').textContent=chatStep===1?'Supplier aur missing quantity/rate bharein. Abhi Tally entry nahi hogi.':'Original bill se invoice/date, GST aur total match karein. Save ke baad validated preview banayein.';
    get('billChatPrevious').hidden=chatStep===1;
    get('billChatNext').hidden=chatStep===2;
    // Keep all underlying controls and values: only their presentation changes.
    for(const key of [...keys,...taxKeys,'tax_treatment']){
      const label=form.elements.namedItem(key)?.closest?.('label');
      if(label?.dataset){label.dataset.chatStep=key==='party_name'?'1':'2';delete label.dataset.chatOptional;}
    }
    const companyLabel=company.closest?.('label');if(companyLabel?.dataset)companyLabel.dataset.chatOptional='true';
    for(const key of ['godown','tax_treatment','invoice_discount','round_off']){
      const label=form.elements.namedItem(key)?.closest?.('label');
      if(label?.dataset&&!(form.elements.namedItem(key)?.value&&key!=='godown'&&key!=='tax_treatment'))label.dataset.chatOptional='true';
    }
  }
  document.getElementById('billChatNext')?.addEventListener('click',()=>{
    if(busy)return;
    const inputs=[form.elements.namedItem('party_name'),...lineRows.flatMap(r=>['item_name','quantity','unit','rate'].map(k=>r.inputs[k]))];
    const missing=inputs.find(input=>!input?.value?.trim()||(input.type==='number'&&!input.checkValidity?.()));
    if(missing){document.getElementById('billChatStepHint').textContent='Pehle supplier aur har item ki quantity, unit, rate bharein.';missing.focus?.();return;}
    chatStep=2;paintChatSteps();chatSteps.scrollIntoView?.({block:'start'});
  });
  document.getElementById('billChatPrevious')?.addEventListener('click',()=>{chatStep=1;paintChatSteps();});
  document.getElementById('billChatFull')?.addEventListener('click',()=>{chatSimple=false;paintChatSteps();});

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
    const sourceTax=Object.values(selected?.content?.expected_taxes||{}).some(value=>Number(value)>0);
    const tax=(taxTreatment?.value||sourceTax)?{tax_treatment:taxTreatment.value||null,
      ...Object.fromEntries(taxKeys.map(k=>[k,form.elements.namedItem(k)?.value?.trim()||null])),
      expected_taxes:Object.fromEntries(taxHeads.filter(h=>expectedTaxInputs[h]?.value?.trim()).map(h=>[h,expectedTaxInputs[h].value.trim()])),unsupported_treatments:unsupportedTreatments}:{};
    return {...tax,unsupported_treatments:unsupportedTreatments,...Object.fromEntries(keys.map(k=>[k,form.elements.namedItem(k)?.value?.trim()||null])),
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
    let gross=0n,discount=0n,complete=true;
    const amountInput=value=>value?cents('1',value):0n;
    for(const row of lineRows){
      const amount=cents(row.inputs.quantity.value,row.inputs.rate.value);
      const fixed=amountInput(row.inputs.discount_amount.value);
      const percent=row.inputs.discount_percent.value;
      const percentAmount=amount===null?null:percent?cents(money(amount),percent):0n;
      const roundPercent=n=>{let q=n/100n,r=n%100n;return q+(r>50n||(r===50n&&q%2n)?1n:0n);};
      const off=percentAmount===null||fixed===null?null:fixed+roundPercent(percentAmount);
      if(amount===null||off===null||off>amount||(percent&&row.inputs.discount_amount.value)){complete=false;row.amount.textContent='Amount pending · check quantity/rate/discount';continue;}
      gross+=amount;discount+=off;
      row.amount.textContent='Before tax: ₹'+money(amount-off)+(off?' · Discount: ₹'+money(off):'');
    }
    if(!complete){totalOutput.textContent='Total pending · check quantity/rate/discount';return;}
    if(!taxTreatment?.value){totalOutput.textContent='Total: ₹'+money(gross)+' (non-GST)';return;}
    if(chatSimple&&(!taxHeads.some(h=>Boolean(expectedTaxInputs[h]?.value))||!form.elements.namedItem('invoice_total')?.value)){
      totalOutput.textContent='Before-tax amount ₹'+money(gross-discount)+' · GST aur final bill total abhi pending';return;
    }
    const header=amountInput(form.elements.namedItem('invoice_discount')?.value||'');
    const taxes=taxHeads.map(h=>amountInput(expectedTaxInputs[h]?.value||''));
    const rawRound=form.elements.namedItem('round_off')?.value||'0';
    const rounding=amountInput(rawRound.replace(/^[-+]/,''));
    if(header===null||rounding===null||taxes.some(x=>x===null)||discount+header>gross){totalOutput.textContent='Total pending · check discount/tax/round-off';return;}
    discount+=header;
    const tax=taxes.reduce((sum,n)=>sum+n,0n),net=gross-discount,final=net+tax+(rawRound.startsWith('-')?-rounding:rounding);
    if(final<0n){totalOutput.textContent='Invalid negative total';return;}
    totalOutput.textContent='Subtotal ₹'+money(gross)+' · Discount ₹'+money(discount)+' · Taxable ₹'+money(net)+' · Tax from bill ₹'+money(tax)+' · Round-off '+(rawRound.startsWith('-')&&rounding?'-':'')+'₹'+money(rounding)+' · Total ₹'+money(final)+(selected?.status==='verified'?' (Tally verified)':' (master verification pending)');
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
        if(ev && ((!ev.source_evidence && ev.unclear) || (ev[key] && ev[key].confidence < 0.80) || (!line[key] && ['item_name','quantity','rate'].includes(key)))){
          input.classList?.add?.('input-unclear');
        }
        input.addEventListener('input',()=>{
          input.classList?.remove?.('input-unclear');
          updateTotals();
        });

        if(!['item_name','quantity','unit','rate'].includes(key)){label.hidden=!taxTreatment?.value;taxLabels.push(label);}
        label.dataset.chatStep=['item_name','quantity','unit','rate'].includes(key)?'1':'2';
        if(['discount_amount','discount_percent'].includes(key)&&!line[key])label.dataset.chatOptional='true';
        label.append(input);box.append(label);inputs[key]=input;
        const source=ev?.source_evidence?.[key];
        if(source && (source.confidence<0.8 || source.suggested_value)){
          const note=document.createElement('p');note.textContent='Original OCR: '+source.raw+' · Re-read: '+(source.reread?.text||'unavailable')+' · Check source before accepting.';label.append(note);
          const inspect=document.createElement('button');inspect.type='button';inspect.textContent='View original '+key+' crop';
          inspect.addEventListener('click',async()=>{
            const stamp=generation;
            try{
              if(!currentDocId)throw new Error('Open the original document first.');
              if(docCurrentPage!==(source.page||1))await loadDocPage(currentDocId,source.page||1);
              const img=docViewer.querySelector('img');if(!img)throw new Error('Original not loaded.');
              await img.decode();if(!valid(stamp))return;
              const [x1,y1,x2,y2]=source.bbox,sx=img.naturalWidth/source.image_width,sy=img.naturalHeight/source.image_height;
              const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.min(1600,Math.round((x2-x1)*sx*4)));canvas.height=Math.max(1,Math.min(512,Math.round((y2-y1)*sy*4)));
              canvas.style.maxWidth='100%';canvas.setAttribute('aria-label','Original bill crop for '+key);
              canvas.getContext('2d').drawImage(img,x1*sx,y1*sy,(x2-x1)*sx,(y2-y1)*sy,0,0,canvas.width,canvas.height);
              label.append(canvas);inspect.disabled=true;
            }catch(error){message.textContent=error.message;}
          });label.append(inspect);
          if(source.suggested_value){
            const use=document.createElement('button');use.type='button';use.textContent='Use Tally suggestion: '+source.suggested_value;
            use.addEventListener('click',()=>{if(busy||selected&&!selected.editable)return;input.value=source.suggested_value;if(form.dataset)form.dataset.dirty='true';input.classList?.remove?.('input-unclear');updateTotals();message.textContent='Suggestion selected. Check original and save draft; no Tally posting.';});label.append(use);
          }
        }
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
      if(ev?.item_name?.raw){
        const remember=document.createElement('button');remember.type='button';remember.textContent='Remember item correction for this company';
        remember.addEventListener('click',()=>rememberCorrection('item',index));box.append(remember);
      }
      box.append(amount,remove);lineHost.append(box);lineRows.push({inputs,amount,remove,taxLabels});
    }
    updateTotals();
  }

  for(const key of ['invoice_discount','round_off'])form.elements.namedItem(key)?.addEventListener('input',updateTotals);

  const scopeNow=()=>JSON.stringify(window.getBusinessChatScope?.()||null);
  const setBusy=value=>{
    busy=value;selectionState();
    for(const id of ['Load','Save','Evaluate'])if(autoEl(id))autoEl(id).disabled=value||(id==='Save'&&automationScope!==company.value)||(id==='Evaluate'&&(!selected||!selected.editable));
    for(const id of ['Mode','Suppliers','Items','Invoice','Amount','Count'])if(autoEl(id))autoEl(id).disabled=value;
    const filter=document.getElementById('billQueueView');if(filter)filter.disabled=value;
    form.querySelectorAll('button').forEach(b=>b.disabled=value);
    for(const key of [...keys,...taxKeys,'tax_treatment']){const el=form.elements.namedItem(key);if(el)el.disabled=value||Boolean(selected&&!selected.editable);}
    for(const row of lineRows){
      for(const input of Object.values(row.inputs))input.disabled=value||Boolean(selected&&!selected.editable);
      row.remove.disabled=value||Boolean(selected&&!selected.editable)||lineRows.length===1;
    }
    document.getElementById('billDraftAddLine').disabled=value||Boolean(selected&&!selected.editable)||lineRows.length>=100;
    for(const input of [...Object.values(expectedTaxInputs),...Object.values(taxLedgerInputs)]){input.disabled=value||Boolean(selected&&!selected.editable);}
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

  const json=(body,method='POST')=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

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
      const sourcePages=(row.extraction_metadata?.source_pages||[1]).filter(page=>Number.isInteger(page)&&page>=1&&page<=docTotalPages);
      await loadDocPage(docId, sourcePages.length?Math.min(...sourcePages):1);
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
    const sourceBlocks=row.content.unsupported_treatments||[];
    if(sourceBlocks.length){const note=document.createElement('p');note.textContent='Posting blocked: '+sourceBlocks.join(', ')+'. Original source review required.';reviewBanner.append(note);}
    const clean=!(meta.warnings&&meta.warnings.length)&&!sourceBlocks.length;
    reviewBanner.className='extraction-review-card'+(clean?' clean':'');

    const badgeRow=document.createElement('div');badgeRow.className='review-badge-row';
    const confScore=Math.round((meta.confidence?.overall ?? 0) * 100);
    const confBadge=document.createElement('span');confBadge.className='badge-confidence';
    confBadge.textContent=meta.source==='chat'?'Chat working copy · invoice/tax review required':confScore?'✧ Extracted · '+confScore+'% extraction confidence'+(row.status==='verified'?'':' (review required)'):'✧ Extracted · confidence unavailable';

    const statusBadge=document.createElement('span');statusBadge.className='badge-review';
    statusBadge.textContent='Status: '+({needs_review:'Review required',verified:'Tally verified',queued:'Posting queued',submitting:'Posting',verification_pending:'Verification pending',preview:'Preview'}[row.status]||'Draft');
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
      if(row.status==='verified'){
        const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Original extraction warnings · retained for audit';details.append(summary,warnList);reviewBanner.append(details);
      }else reviewBanner.append(warnList);
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
    chatSimple=false;chatStep=1;paintChatSteps();
    reviewMeter?.select(null);reviewMeter?.flush().catch(()=>{});
    resetAutomation();
    if(form.dataset)form.dataset.dirty='false';
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
    const sameChat=selected?.id===row.id&&chatSimple;
    if(selected?.company_id!==row.company_id)resetAutomation();
    if(form.dataset)form.dataset.dirty='false';
    selected=row;company.value=row.company_id;company.disabled=true;
    if(receiptPanel){receiptPanel.open=false;receiptPanel.hidden=!row.editable||!row.content.invoice_number||!!row.extraction_metadata?.goods_receipt;}
    reviewMeter?.select(row.editable?{id:row.id,revision:row.revision,scope:scopeNow()}:null);
    for(const key of [...keys,...taxKeys,'tax_treatment']){
      const input=form.elements.namedItem(key);
      if(input){input.value=key==='round_off'&&row.content[key]!=null&&Number(row.content[key])===0?'0.00':row.content[key]??'';input.disabled=!row.editable;
        const evidence=row.extraction_metadata?.field_evidence?.[key];
        input.classList?.toggle?.('input-unclear',Boolean(evidence&&(evidence.confidence??0)<0.8));
      }
    }
    unsupportedTreatments=row.content.unsupported_treatments||[];
    for(const h of taxHeads){if(expectedTaxInputs[h])expectedTaxInputs[h].value=row.content.expected_taxes?.[h]??'';}
    const sourceTaxes=Object.values(row.content.expected_taxes||{}).some(value=>Number(value)>0);
    if(taxTreatment?.options?.[0])taxTreatment.options[0].textContent=sourceTaxes&&!row.content.tax_treatment?'GST source · treatment needs review':'Non-GST / no tax fields';
    const taxFields=document.getElementById('billDraftTaxFields');if(taxFields)taxFields.hidden=!(row.content.tax_treatment||sourceTaxes);
    chatSimple=row.extraction_metadata?.source==='chat'&&row.editable;
    if(!sameChat)chatStep=1;
    renderLines(normalLines(row.content), row.extraction_metadata?.line_evidence || []);
    if(sourceTaxes)for(const line of lineRows)for(const label of line.taxLabels)label.hidden=false;
    paintChatSteps();
    renderExtractionBanner(row);
    document.getElementById('billDraftSave').hidden=!row.editable;
    document.getElementById('billDraftMakePreview').hidden=!row.editable;
    message.textContent='Revision '+row.revision+' · '+row.status;
    const stamp=generation,ticket=++decisionRequest;api('/'+row.id+'/automation-decisions').then(data=>{if(ticket===decisionRequest&&valid(stamp)&&selected?.id===row.id)renderDecisions(data.decisions);}).catch(()=>{});
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

  async function openQueueBill(row){
    if(busy)return;
    if(selected&&selected.editable&&form.dataset?.dirty==='true'){message.textContent='Save edits before changing bills.';return;}
    if(row.kind==='document'){message.textContent=row.review_reason;return;}
    setBusy(true);const stamp=generation;
    try{
      const current=await api('/'+row.id),events=await api('/'+row.id+'/audit');
      await loadMasters(current.company_id,stamp);if(!valid(stamp))return;
      preview.replaceChildren();show(current);showAudit(events.events);
      await setupSideBySide(current);if(current.content.tax_treatment)await loadTaxSetup(current.company_id,stamp);
    }catch(error){if(valid(stamp))message.textContent=error.message;}
    finally{if(stamp===generation)setBusy(false);}
  }

  async function listing(id) {
    const ticket=++queueGeneration;queueLoading=true;queueSelection.clear();selectionState();
    try{
    const data=await api('/review-queue?view='+queueView+'&offset='+queueOffset+'&limit=50');if(!valid(id)||ticket!==queueGeneration)return;
    queueRows=data.bills;queueSelection.clear();selectionState();queueButtons=[];
    const counts=document.getElementById('billQueueCounts');
    if(counts)counts.textContent=Object.entries(data.counts).map(([k,v])=>k.replace('_',' ')+': '+v).join(' · ');
    const previous=document.getElementById('billQueuePrevious'),next=document.getElementById('billQueueNext');
    if(previous)previous.disabled=queueOffset===0;
    if(next)next.disabled=queueOffset+50>=data.total;
    list.replaceChildren();
    if(!queueRows.length){list.textContent='No bills in this view.';return;}
    for(const row of queueRows){
      const button=document.createElement('button');button.type='button';
      const lines=row.content?normalLines(row.content):[],inv=row.content?.invoice_number;
      button.textContent=(row.document_filename||row.content?.party_name||'Incomplete purchase')+(inv?' ['+inv+']':'')+' · '+(lines[0]?.item_name||'')+' · '+row.queue_bucket;
      button.addEventListener('click',()=>openQueueBill(row));list.append(button);queueButtons.push(button);
      if(row.ready){
        const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';
        check.setAttribute('aria-label','Select '+(inv||row.id));
        check.addEventListener('change',()=>{if(queueLoading||busy)return;if(check.checked)queueSelection.set(row.id,{draft_id:row.id,revision:row.revision,action_id:row.action_id});else queueSelection.delete(row.id);selectionState();});
        label.append(check,document.createTextNode?.(' Approve this reviewed bill')||' Approve this reviewed bill');list.append(label);
      }
    }
    }finally{if(ticket===queueGeneration){queueLoading=false;selectionState();}}
  }

  document.getElementById('billQueueView')?.addEventListener('change',async event=>{
    if(busy)return;queueView=event.target.value;queueOffset=0;
    try{await listing(generation);}catch(e){message.textContent=e.message;}
  });
  for(const [id,delta] of [['billQueuePrevious',-50],['billQueueNext',50]])document.getElementById(id)?.addEventListener('click',async()=>{
    if(busy)return;queueOffset=Math.max(0,queueOffset+delta);
    try{await listing(generation);}catch(e){message.textContent=e.message;}
  });
  document.getElementById('billQueueSelectReady')?.addEventListener('click',()=>{
    if(busy||queueLoading)return;
    for(const check of list.querySelectorAll('input[type="checkbox"]')){check.checked=true;check.dispatchEvent(new Event('change'));}
  });
  queueApprove?.addEventListener('click',async()=>{
    if(busy||queueLoading||!queueSelection.size)return;
    if(selected&&queueSelection.has(selected.id)&&form.dataset?.dirty==='true'){message.textContent='Save & validate edits before approving this bill.';return;}
    const stamp=generation,items=Array.from(queueSelection.values());setBusy(true);
    try{
      const data=await api('/bulk-approve',json({items},'POST'));if(!valid(stamp))return;
      const host=document.getElementById('billQueueResults');host.replaceChildren();
      for(const result of data.results){const p=document.createElement('p');p.textContent=result.draft_id+' · '+(result.ok?'Queued':'Needs attention')+' · '+result.response;host.append(p);}
      message.textContent=data.approved+' queued · '+data.failed+' need attention.';
      if(selected){const current=await api('/'+selected.id);if(valid(stamp)){show(current);preview.replaceChildren();}}
      await listing(stamp);
    }catch(e){if(valid(stamp))message.textContent='Approval result unavailable. Refresh queue before another attempt. '+e.message;}
    finally{if(stamp===generation)setBusy(false);}
  });
  function nextIssue(){
    const missing=[...['party_name','entry_date'].map(k=>form.elements.namedItem(k)),...lineRows.flatMap(r=>['item_name','quantity','unit','rate'].map(k=>r.inputs[k]))].filter(el=>el&&!el.disabled&&!el.value.trim());
    const issues=Array.from(new Set([...form.querySelectorAll('input.input-unclear, select.input-unclear, input:invalid'),...missing])).filter(el=>!el.disabled);
    if(!issues.length){message.textContent='No highlighted fields. Save & validate to check masters and totals.';return;}
    const current=issues.indexOf(document.activeElement);issues[(current+1)%issues.length].focus();
  }
  document.getElementById('billQueueNextIssue')?.addEventListener('click',nextIssue);
  dialog.addEventListener('keydown',event=>{
    if(!event.altKey||busy)return;
    if(event.key.toLowerCase()==='n'){event.preventDefault();nextIssue();}
    if(['ArrowDown','ArrowUp'].includes(event.key)){
      event.preventDefault();const index=queueRows.findIndex(r=>r.id===selected?.id),direction=event.key==='ArrowDown'?1:-1;
      const next=index<0?0:Math.max(0,Math.min(queueRows.length-1,index+direction));
      if(queueRows[next])openQueueBill(queueRows[next]);
    }
  });
  form.addEventListener('input',()=>{if(form.dataset)form.dataset.dirty='true';});
  document.getElementById('billQueueValidate')?.addEventListener('click',async()=>{
    if(busy||!selected||!selected.editable)return;const stamp=generation;setBusy(true);
    try{
      const row=await api('/'+selected.id,json({revision:selected.revision,content:contentNow()},'PUT'));
      if(!valid(stamp))return;show(row);setBusy(false);
      await makePreview();
    }catch(e){if(valid(stamp))message.textContent=e.message;}
    finally{if(stamp===generation&&busy)setBusy(false);}
  });

  async function load() {
    queueOffset=0;queueSelection.clear();
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
    queueOffset=0;queueSelection.clear();
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
    reviewMeter?.select(null);reviewMeter?.flush().catch(()=>{});
    generation++;queueGeneration++;queueLoading=false;scope=null;busy=false;queueRows=[];queueSelection.clear();queueOffset=0;queueView='all';
    document.getElementById('billQueueView').value='all';
    document.getElementById('billQueueResults').replaceChildren();document.getElementById('billQueueCounts').textContent='';
    clear();list.replaceChildren();company.replaceChildren();itemMasters=[];
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
    label.textContent=head+' amount from original ₹';input.type='number';input.min='0';input.step='0.01';input.addEventListener('input',updateTotals);label.append(input);taxHost.append(label);expectedTaxInputs[head]=input;}}
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
    resetAutomation();
    if(busy)return;const id=generation;setBusy(true);
    try{await loadMasters(company.value,id);}catch(error){if(valid(id))message.textContent=error.message;}finally{if(id===generation)setBusy(false);}
  });

  async function rememberCorrection(kind,lineIndex=null){
    if(busy||!selected||!selected.editable)return;const stamp=generation;setBusy(true);
    try{
      const saved=await api('/'+selected.id,json({revision:selected.revision,content:contentNow()},'PUT'));
      if(!valid(stamp))return;show(saved);
      const row=await api('/'+saved.id+'/aliases',json({revision:saved.revision,kind,line_index:lineIndex},'POST'));
      if(!valid(stamp))return;show(row);preview.replaceChildren();
      message.textContent='Correction approved for this company. It will be reused only while the exact Tally master is unchanged.';
      await listing(stamp);
    }catch(e){if(valid(stamp))message.textContent=e.message;}
    finally{if(stamp===generation)setBusy(false);}
  }
  document.getElementById('billRememberSupplier')?.addEventListener('click',()=>rememberCorrection('supplier'));
  document.getElementById('billCompanyMemory')?.addEventListener('click',async()=>{
    if(busy||!company.value)return;const stamp=generation;setBusy(true);
    try{
      const data=await api('/companies/'+company.value+'/aliases');if(!valid(stamp))return;preview.replaceChildren();
      for(const alias of data.aliases){const line=document.createElement('p');line.textContent=alias.kind+': '+alias.source+' → '+alias.target+' · '+(alias.valid?'Approved':'Master changed — correction needs review');preview.append(line);}
      if(!data.aliases.length)message.textContent='No approved corrections in this company yet.';
    }catch(e){if(valid(stamp))message.textContent=e.message;}
    finally{if(stamp===generation)setBusy(false);}
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

  async function makePreview(){
    if(busy||!selected)return;
    if(scope!==scopeNow()){dialog.close();return;}
    const savedTax=(selected.content.tax_treatment||Object.values(selected.content.expected_taxes||{}).some(value=>Number(value)>0))?{tax_treatment:selected.content.tax_treatment||null,...Object.fromEntries(taxKeys.map(k=>[k,selected.content[k]??null])),expected_taxes:selected.content.expected_taxes||{},unsupported_treatments:selected.content.unsupported_treatments||[]}:{};
    if(savedTax.round_off!=null&&Number(savedTax.round_off)===0)savedTax.round_off='0.00';
    const saved={...savedTax,unsupported_treatments:selected.content.unsupported_treatments||[],...Object.fromEntries(keys.map(k=>[k,selected.content[k]??null])),lines:normalLines(selected.content)};
    if(JSON.stringify(contentNow())!==JSON.stringify(saved)){message.textContent='Pehle edited draft save karein.';return;}
    const id=generation;setBusy(true);
    try{
      const data=await api('/'+selected.id+'/preview',json({revision:selected.revision},'POST'));
      if(!valid(id))return;preview.replaceChildren();message.textContent=data.response;
      for(const text of data.preview.lines){const line=document.createElement('p');line.textContent=text;preview.append(line);}
      if(data.preview.can_confirm===false){
        for(const blocker of data.preview.blockers||[]){const note=document.createElement('p');note.textContent=blocker;preview.append(note);}
        const refreshed=await api('/'+selected.id);if(valid(id)){show(refreshed);await listing(id);}return;
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
  }
  document.getElementById('billDraftMakePreview').addEventListener('click',makePreview);

  const workspace=document.getElementById('workspaceSelect');
  workspace?.addEventListener('change',()=>{if(dialog.open)dialog.close();});
  document.getElementById('businessSignOut').addEventListener('click',()=>{if(dialog.open)dialog.close();});
})();
