// Business conversation uses its own authenticated route; no legacy CRM actions.
(() => {
  const input = document.getElementById('businessInput');
  const send = document.getElementById('businessSend');
  const welcome = document.getElementById('businessWelcome');
  const messages = document.getElementById('businessMessages');
  const scroll = document.getElementById('businessScroll');
  const dialog = document.getElementById('businessConnections');
  const status = document.getElementById('businessVoiceStatus');
  const mic = document.getElementById('businessMic');
  const root = document.getElementById('businessApp');
  const menu = document.getElementById('businessMobileMenu');
  const backdrop = document.createElement('button');
  backdrop.type = 'button'; backdrop.className = 'business-nav-backdrop';
  backdrop.setAttribute('aria-label', 'Close chat menu'); root.append(backdrop);
  const closeMenu = () => { root.classList.remove('nav-open'); menu.setAttribute('aria-expanded', 'false'); };
  menu.addEventListener('click', () => { root.classList.toggle('nav-open'); menu.setAttribute('aria-expanded', String(root.classList.contains('nav-open'))); });
  backdrop.addEventListener('click', closeMenu);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); });
  let busy = false, voiceActive = false, epoch = 0, history = [];
  let requestController = null;
  let transcript=[], activeScope=null;
  let conversationId=null, conversationRevision=0, chatSummaries=[], loadingChat=false, restorePromise=null;
  let saveQueue=Promise.resolve();
  let serverSaveFailed=false;
  const chatList=document.getElementById('businessChatList');
  let browserStorage, legacyStorage, storageWarning='';
  try{browserStorage=window.localStorage;}catch{browserStorage=null;}
  try{legacyStorage=window.sessionStorage;}catch{legacyStorage=null;}
  const store=window.createBusinessChatStore(browserStorage,legacyStorage);
  const persist=()=>{
    if(!activeScope)return;
    storageWarning=store.write(transcript)?'':'Chat save nahi hui: browser storage unavailable.';
    if(storageWarning)status.textContent=storageWarning;
    if(!loadingChat&&transcript.length)queueChatSave();
  };
  async function chatApi(path,options={}) {
    const response=await window.fetchWithAuth('/api/v1/business/conversations'+path,options);
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Chat save/load nahi hui.');
    return data;
  }
  function renderChatList() {
    chatList.replaceChildren();
    if(!chatSummaries.length){const empty=document.createElement('span');empty.className='business-history-empty';empty.textContent='Saved chats yahan dikhenge.';chatList.append(empty);}
    for(const chat of chatSummaries){
      const button=document.createElement('button');button.type='button';button.textContent=chat.title;button.title=chat.title;
      button.setAttribute('aria-current',String(chat.id===conversationId));
      button.addEventListener('click',()=>{if(!busy&&!loadingChat)openChat(chat.id);});chatList.append(button);
    }
  }
  function queueChatSave() {
    const scope=activeScope, id=epoch, snapshot=JSON.parse(JSON.stringify(transcript));
    saveQueue=saveQueue.then(async()=>{
      if(scope!==activeScope||id!==epoch)return;
      if(!conversationId){
        const created=await chatApi('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({organization_id:JSON.parse(scope).organization_id})});
        if(scope!==activeScope||id!==epoch)return;
        conversationId=created.id;conversationRevision=created.revision;store.selectConversation(conversationId);
      }
      const updated=await chatApi('/'+encodeURIComponent(conversationId),{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({revision:conversationRevision,messages:snapshot})});
      if(scope!==activeScope||id!==epoch)return;
      conversationRevision=updated.revision;
      serverSaveFailed=false;
      chatSummaries=[updated,...chatSummaries.filter(chat=>chat.id!==updated.id)].slice(0,100);renderChatList();
    }).catch(error=>{if(scope===activeScope&&id===epoch){serverSaveFailed=true;storageWarning=error.message+' Browser copy rakhi gayi hai.';status.textContent=storageWarning;}});
  }
  async function openChat(chatId) {
    const scope=activeScope;
    loadingChat=true;
    await saveQueue;
    if(serverSaveFailed){status.textContent='Current chat save nahi hui. Pehle connection restore karke retry karein.';loadingChat=false;return;}
    try {
      const data=await chatApi('/'+encodeURIComponent(chatId));
      if(scope!==activeScope)return;
      reset();conversationId=data.id;conversationRevision=data.revision;store.selectConversation(conversationId);
      transcript=data.messages;renderTranscript();store.write(transcript);renderChatList();closeMenu();
    }catch(error){if(scope===activeScope)status.textContent=error.message;}
    finally{loadingChat=false;resize();}
  }
  const audioUrls = new Set();
  const reset = () => {
    epoch++; requestController?.abort(); voice.cancel(); busy = false; history = [];
    transcript=[];storageWarning='';serverSaveFailed=false;
    messages.querySelectorAll('audio').forEach(audio => audio.pause());
    audioUrls.forEach(url => URL.revokeObjectURL(url)); audioUrls.clear();
    messages.replaceChildren(); welcome.hidden = false; input.value = ''; status.textContent = ''; resize();
  };
  const voice = window.createBusinessVoice({
    onTranscript: text => submit(text, true),
    onStatus: text => { status.textContent = text; },
    onActive: active => {
      voiceActive = active; mic.setAttribute('aria-pressed', String(active));
      mic.setAttribute('aria-label', active ? 'Recording roko' : 'AI se bolkar baat karein'); resize();
    }
  });

  const resize = () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 130) + 'px';
    send.disabled = busy || voiceActive || !input.value.trim();
    mic.disabled = busy;
  };
  const connect = () => { closeMenu(); if (!dialog.open) dialog.showModal(); window.openBusinessTally?.(); };
  document.getElementById('businessConnectionBtn').addEventListener('click', connect);
  document.getElementById('businessConnectionTop').addEventListener('click', connect);
  document.getElementById('businessCloseConnections').addEventListener('click', () => dialog.close());
  document.getElementById('businessBackToChat').addEventListener('click', () => dialog.close());
  document.getElementById('businessSignOut').addEventListener('click', () => {
    closeMenu();
    activeScope=null;store.scope(null);
    chatSummaries=[];conversationId=null;renderChatList();
    reset();
    messages.replaceChildren();
    welcome.hidden = false;
    input.value = '';
    resize();
    document.getElementById('logoutBtn').click();
  });
  const workspace = document.getElementById('workspaceSelect');
  if (workspace) {
    document.getElementById('businessWorkspaceSlot').append(workspace);
    workspace.addEventListener('change', () => {
      reset(); activeScope=null;store.scope(null);
      chatSummaries=[];conversationId=null;renderChatList();
    });
  }
  document.querySelectorAll('[data-business-prompt]').forEach(button => {
    button.addEventListener('click', () => {
      input.value = button.dataset.businessPrompt;
      resize(); input.focus();
    });
  });
  document.getElementById('businessNewChat').addEventListener('click', () => {
    if(busy||loadingChat)return;
    const scope=activeScope;loadingChat=true;
    saveQueue.then(()=>{
      if(scope!==activeScope)return;
      if(serverSaveFailed){status.textContent='Current chat save nahi hui. New chat se pehle connection restore karke retry karein.';return;}
      closeMenu();store.clear();store.selectConversation('new');
      reset();conversationId=null;conversationRevision=0;renderChatList();input.focus();
    }).finally(()=>{loadingChat=false;resize();});
  });
  function addMessage(text, role, offerConnection = false, restored = null) {
    const record=restored||{text,role};
    if(!restored){transcript.push(record);transcript=transcript.slice(-300);persist();}
    const node = document.createElement('div');
    node.chatRecord=record;
    node.className = 'business-message ' + role;
    const messageText = document.createElement('span');
    messageText.className = 'business-message-text'; messageText.textContent = text;
    node.append(messageText);
    if (offerConnection) {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = 'Connection details';
      button.addEventListener('click', connect); node.append(button);
    }
    messages.append(node);
    scroll.scrollTop = scroll.scrollHeight;
    return node;
  }
  async function submit(text, spoken = false, command = {}) {
    if(!activeScope)await restoreChat();
    if(!activeScope){status.textContent='Chat session load nahi hui. Page refresh karke dobara try karein.';return;}
    text = text.trim(); if (!text || busy || loadingChat || root.inert) return;
    voice.cancel(); welcome.hidden = true; busy = true;
    const id = epoch;
    requestController = new AbortController();
    addMessage(text, 'user'); input.value = ''; resize();
    status.textContent = 'Soch raha hoon…';
    try {
      await saveQueue;
      if(id!==epoch)return;
      const response = await window.fetchWithAuth('/api/v1/business/command', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        signal: requestController.signal,
        body: JSON.stringify({ text, conversation_history: history.slice(-10), ...command })
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        const issues=Array.isArray(error.detail)?error.detail:[];
        const fieldNames={rate:'Rate per bag',quantity:'Quantity',party_name:'Supplier',unit:'Unit',entry_date:'Entry date'};
        const details=issues.map(issue=>{
          const key=issue.loc?.[issue.loc.length-1];
          if(key==='rate' && issue.type==='decimal_max_places')return 'Rate mein maximum 2 decimal places dalein, jaise 199.04.';
          return (fieldNames[key] || key || 'Details')+': '+issue.msg;
        }).join(' ');
        throw new Error(typeof error.detail === 'string' ? error.detail : details || 'Baat process nahi hui. Details check karke dobara try karein.');
      }
      const data = await response.json();
      if (id !== epoch) return;
      const node = addMessage(data.tasks ? data.response.split('\n')[0] : data.response, 'assistant');
      renderTools(node, data, text);
      scroll.scrollTop = scroll.scrollHeight;
      history.push({role:'user',content:text},{role:'assistant',content:data.response.slice(0,4000)});
      await saveQueue;
      if(id!==epoch)return;
      history = history.slice(-10); status.textContent = storageWarning;
      if (spoken) {
        status.textContent = 'Jawab ki awaaz bana raha hoon…';
        try {
          const speech = await window.fetchWithAuth('/api/v1/voice/speak', {
            method:'POST', headers:{'Content-Type':'application/json'},
            signal:requestController.signal, body:JSON.stringify({text:data.response.slice(0,2500)})
          });
          if (!speech.ok) throw new Error('speech');
          const blob = await speech.blob();
          if (id !== epoch) return;
          if (!blob.size) throw new Error('empty speech');
          const url = URL.createObjectURL(blob); audioUrls.add(url);
          const audio = document.createElement('audio'); audio.src = url; audio.controls = true;
          audio.setAttribute('aria-label','Assistant ka jawab sunein'); node.append(audio);
          audio.onended = () => { if (id === epoch) status.textContent = 'Agli baat ke liye mic dabayein.'; };
          try { await audio.play(); status.textContent = 'Jawab suniyega…'; }
          catch { status.textContent = 'Jawab sunne ke liye play dabayein.'; }
        } catch (error) {
          if (id === epoch) status.textContent = 'Awaaz nahi bani. Jawab upar text mein hai.';
        }
      }
    } catch (error) {
      if (id === epoch) {
        addMessage(error.message || 'AI se jawab nahi aa paya. Dobara try karein.', 'assistant');
        input.value = text; status.textContent = 'Message dobara bhej sakte hain.';
      }
    } finally {
      if (id === epoch) { busy = false; requestController = null; resize(); }
    }
  }
  function toolButton(parent, label, handler) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
    button.addEventListener('click', () => { if (!busy && !root.inert) handler(); }); parent.append(button); return button;
  }
  function renderTools(node, data, originalText) {
    if(node.chatRecord){node.chatRecord.data=data;node.chatRecord.originalText=originalText;persist();}
    if (data.source_meetings?.length) {
      const sources = document.createElement('p');
      sources.className = 'business-hint';
      sources.textContent = 'Sources: ' + data.source_meetings.map(source => `${source.label} · ${source.date}`).join('; ');
      node.append(sources);
    }
    const tools = document.createElement('div'); tools.className = 'business-tools'; node.append(tools);
    const messageText = node.querySelector('.business-message-text');
    window.renderBusinessTally?.(tools, data, {submit, toolButton, connect,
      updateMessage:messageText ? text=>{messageText.textContent=text;if(node.chatRecord){node.chatRecord.text=text;persist();}return messageText;} : undefined,
      updateState:result=>{if(node.chatRecord){node.chatRecord.data={...node.chatRecord.data,...result};persist();}},
      renderResult:(target,result)=>renderTools(target,result,originalText)});
    if (data.choices) {
      data.choices.forEach(customer => toolButton(tools, customer.name, () => submit(originalText || 'Customer details', false,
        {...data.selection_command, client_id: customer.id})));
      toolButton(tools, '+ Customer add karein', () => showToolForm(tools, 'customer_create'));
    }
    if (data.customer) {
      toolButton(tools, 'Contact update', () => showToolForm(tools, 'customer_update', data.customer));
      toolButton(tools, '+ Follow-up', () => showToolForm(tools, 'task_create', data.customer));
      toolButton(tools, 'Message draft', () => showToolForm(tools, 'reminder_draft', data.customer));
    }
    if (data.tasks) {
      data.tasks.forEach(task => {
        const card = document.createElement('div'); card.className = 'business-task-card';
        const label = document.createElement('p'); label.textContent = `${task.customer}: ${task.description}\n${task.due_date || 'Date nahi hai'}${task.overdue ? ' · Overdue' : ''}`; card.append(label);
        toolButton(card, 'Done', () => submit('Ye kaam completed mark karo', false, {intent:'task_complete', fields:{task_id:task.id}})); tools.append(card);
      });
    }
    if (data.preview) {
      const preview = data.preview;
      const card = document.createElement('div'); card.className = 'business-preview-card';
      const title = document.createElement('strong'); title.textContent = preview.title; card.append(title);
      preview.lines.forEach(line => { const p = document.createElement('p'); p.textContent = line; card.append(p); });
      preview.blockers.forEach(line => { const p = document.createElement('p'); p.className = 'business-blocker'; p.textContent = line; card.append(p); });
      const approve = toolButton(card, preview.send ? 'Confirm & send' : 'Confirm & save', () => approvePreview(preview.token, true, card));
      approve.disabled = !preview.can_confirm;
      const cancel=toolButton(card, 'Cancel', () => approvePreview(preview.token, false, card));
      cancel.disabled=!preview.can_confirm;tools.append(card);
    }
  }
  function showToolForm(parent, intent, customer = null) {
    parent.querySelector('form')?.remove();
    const form = document.createElement('form'); form.className = 'business-tool-form';
    const field = (name, label, type = 'text', required = false, value = '') => {
      const wrap = document.createElement('label'); wrap.textContent = label;
      const control = document.createElement('input'); control.name = name; control.type = type; control.required = required; control.value = value; control.maxLength = 500; wrap.append(control); form.append(wrap); return control;
    };
    if (intent === 'customer_create') field('client_name','Customer ka naam','text',true).maxLength = 120;
    if (intent === 'customer_create' || intent === 'customer_update') {
      field('email','Email','email',false,customer?.email || '');
      field('whatsapp_phone','WhatsApp number (country code ke saath)','tel',false,customer?.whatsapp_phone || '');
    } else {
      field('description',intent === 'task_create' ? 'Kya kaam karna hai?' : 'Kya message bhejna hai?','text',true);
      if (intent === 'task_create') field('due_date','Kis date ko?','date',true);
      else {
        const label = document.createElement('label'); label.textContent = 'Kahan bhejna hai?';
        const select = document.createElement('select'); select.name = 'channel';
        [['email','Email'],['whatsapp','WhatsApp'],['both','Dono']].forEach(([value,text]) => { const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option); });
        label.append(select); form.append(label);
      }
    }
    const button = document.createElement('button'); button.type = 'submit'; button.textContent = 'Preview dekhein'; form.append(button);
    form.addEventListener('submit', event => {
      event.preventDefault(); if (busy || root.inert || voiceActive) return;
      const fields = Object.fromEntries(new FormData(form));
      if (fields.whatsapp_phone) fields.whatsapp_phone = fields.whatsapp_phone.replace(/[\s()-]/g,'');
      Object.keys(fields).forEach(key => { if (!fields[key]) delete fields[key]; });
      if (customer) fields.client_name = customer.name;
      submit(`${customer?.name || fields.client_name || ''}: ${intent === 'task_create' ? 'follow-up preview' : intent === 'reminder_draft' ? 'message preview' : 'customer preview'}`, false,
        {intent,fields,...(customer ? {client_id:customer.id} : {})});
    });
    parent.append(form); form.querySelector('input')?.focus(); scroll.scrollTop = scroll.scrollHeight;
  }
  async function approvePreview(token, approve, card) {
    if (busy || root.inert || voiceActive) return;
    busy = true; const id = epoch; resize();
    const buttons = card.querySelectorAll('button'); buttons.forEach(button => { button.disabled = true; });
    transcript.forEach(record=>{if(record.data?.preview?.token===token)record.data.preview.can_confirm=false;});persist();
    requestController = new AbortController(); status.textContent = approve ? 'Process kar raha hoon…' : 'Cancel kar raha hoon…';
    try {
      const response = await window.fetchWithAuth('/api/v1/business/confirm', {method:'POST',headers:{'Content-Type':'application/json'},
        signal:requestController.signal,body:JSON.stringify({token,approve})});
      const data = await response.json().catch(() => ({})); if (id !== epoch) return;
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Action complete nahi hua. Status check karein.');
      const resultNode = addMessage(data.response,'assistant'); renderTools(resultNode, data, 'Status check'); history.push({role:'assistant',content:data.response.slice(0,4000)}); history = history.slice(-10);
      status.textContent = '';
    } catch (error) {
      if (id === epoch) { const errorNode=addMessage(error.message || 'Status nahi mila. Dobara send na karein; pehle records check karein.','assistant'); renderTools(errorNode, {tally_action:token,response:errorNode.chatRecord.text}, 'Status check'); status.textContent = ''; }
    } finally { if (id === epoch) {busy = false; requestController = null; resize();} }
  }
  document.querySelectorAll('[data-business-command]').forEach(button => {
    button.addEventListener('click', () => { closeMenu(); submit(button.textContent.trim(), false, {intent:button.dataset.businessCommand,fields:button.dataset.businessCommand === 'task_list' ? {when:button.dataset.businessFilter || 'today'} : {}}); });
  });
  document.getElementById('businessComposer').addEventListener('submit', event => {
    event.preventDefault(); if (!voiceActive) submit(input.value);
  });
  input.addEventListener('input', resize);
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); document.getElementById('businessComposer').requestSubmit();
    }
  });
  mic.addEventListener('click', () => {
    if (busy) return;
    messages.querySelectorAll('audio').forEach(audio => audio.pause());
    voice.toggle();
  });
  window.addEventListener('pagehide', () => {persist();requestController?.abort();voice.cancel();});
  async function restoreChat() {
    const scope=window.getBusinessChatScope?.();
    if(!scope||!scope.user_id||!scope.organization_id||!scope.session_id)return;
    const signature=JSON.stringify(scope);if(signature===activeScope){await restorePromise;return;}
    restorePromise=(async()=>{
      reset();activeScope=signature;store.scope(scope);conversationId=null;conversationRevision=0;loadingChat=true;
      const cached=store.read(), selected=store.conversation();
      transcript=cached;
      try {
        const list=await chatApi('');if(signature!==activeScope)return;
        chatSummaries=list.conversations;
        const selectedChat=selected==='new'?null:chatSummaries.find(chat=>chat.id===selected)||chatSummaries[0];
        if(selectedChat){
          const saved=await chatApi('/'+encodeURIComponent(selectedChat.id));if(signature!==activeScope)return;
          conversationId=saved.id;conversationRevision=saved.revision;transcript=saved.messages;store.selectConversation(conversationId);
        }
      }catch(error){if(signature===activeScope)storageWarning=error.message+' Browser copy dikhayi gayi hai.';}
      if(signature!==activeScope)return;
      renderTranscript();renderChatList();loadingChat=false;
      if(!conversationId&&transcript.length)persist();
      status.textContent=storageWarning;
    })();
    try{await restorePromise;}finally{if(signature===activeScope){restorePromise=null;loadingChat=false;resize();}}
  }
  function renderTranscript() {
    const id=epoch;
    for(const record of transcript){
      const node=addMessage(record.text,record.role,false,record);
      if(record.data)try{renderTools(node,record.data,record.originalText);}catch{node.querySelectorAll('.business-tools').forEach(tool=>tool.remove());}
      if(record.role==='assistant'&&record.data?.tally_action&&(!record.data.preview||!record.data.preview.can_confirm)){
        // Status-only reconciliation never resends the approved voucher.
        window.fetchWithAuth('/api/v1/integrations/tally/actions/'+encodeURIComponent(record.data.tally_action)+'/reconcile',{
          method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
        }).then(async response=>{if(!response.ok)return;const result=await response.json();if(id!==epoch)return;
          record.text=result.response||record.text;record.data={...record.data,...result};
          if(result.sync_status&&result.sync_status!=='draft'&&!result.preview)delete record.data.preview;
          node.querySelector('.business-message-text').textContent=record.text;
          node.querySelectorAll('.business-tools').forEach(tool=>tool.remove());renderTools(node,record.data,record.originalText);
        }).catch(()=>{});
      }
    }
    history=transcript.map(record=>({role:record.role,content:record.text.slice(0,4000)})).slice(-10);
    welcome.hidden=transcript.length>0;scroll.scrollTop=scroll.scrollHeight;
  }
  window.addEventListener('business-auth-ready',restoreChat);
  // Keep legacy authentication behavior, while replacing its CRM-specific copy.
  const authTitle = document.getElementById('authTitle');
  const authSubtitle = document.getElementById('authSubtitle');
  const updateAuthCopy = () => {
    if (authTitle.textContent === 'Sign in to Philixa') authSubtitle.textContent = 'Stock, hisab aur daily kaam — ek conversation mein.';
    if (authTitle.textContent === 'Create your Workspace') authSubtitle.textContent = 'Apne business ke liye workspace banayein.';
  };
  new MutationObserver(updateAuthCopy).observe(authTitle, {childList:true});
  const authModal = document.getElementById('authModal');
  const syncAuth = () => {
    root.inert = !authModal.classList.contains('hidden');
    if (root.inert) {
      closeMenu(); reset();
      activeScope=null;store.scope(null);
      chatSummaries=[];conversationId=null;renderChatList();
      welcome.hidden = false; input.value = ''; resize();
    }else restoreChat();
  };
  new MutationObserver(syncAuth).observe(authModal, {attributes:true,attributeFilter:['class']});
  syncAuth();
  updateAuthCopy(); resize();
})();
