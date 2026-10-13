// Browser persistence per authenticated user/workspace. Never replay commands.
window.createBusinessChatStore = (storage, legacyStorage = storage) => {
  let key=null, legacyKey=null, sessionId=null;
  const stores=()=>[...new Set([storage,legacyStorage].filter(Boolean))];
  const readValue=(source,entry)=>{
    try {
      const raw=source?.getItem(entry);if(!raw||raw.length>2500000)return null;
      const value=JSON.parse(raw);
      if(![1,2].includes(value.version)||!Array.isArray(value.messages)||value.messages.length>300)return null;
      return value;
    }catch{return null;}
  };
  const write=messages=>{
    if(!key)return false;
    const raw=JSON.stringify({version:2,session_id:sessionId,messages:messages.slice(-300)});
    for(const source of stores())try{source.setItem(key,raw);return true;}catch{}
    return false;
  };
  return {
    scope(scope) {
      key=scope?.user_id&&scope?.organization_id&&scope?.session_id
        ?'philixa:chat:v2:'+JSON.stringify([scope.user_id,scope.organization_id]):null;
      sessionId=scope?.session_id||null;
      legacyKey=key?'philixa:chat:v1:'+JSON.stringify([scope.user_id,scope.organization_id,scope.session_id]):null;
    },
    read() {
      if(!key)return [];
      const value=stores().map(source=>readValue(source,key)).find(Boolean)
        || readValue(legacyStorage,legacyKey);
      if(!value)return [];
      const messages=value.messages.filter(m=>m&&['user','assistant'].includes(m.role)&&typeof m.text==='string'&&m.text.length<=100000&&(!m.data||typeof m.data==='object'));
      if(value.version===2&&value.session_id!==sessionId){
        for(const message of messages)if(message.data?.preview){
          message.data.preview={...message.data.preview,can_confirm:false,
            blockers:['Ye preview pichhli login session ka hai. Naya preview banayein.']};
        }
      }
      if(value.version===1)write(messages); // Keep existing same-tab chats.
      return messages;
    },
    write,
    conversation(){try{return key?JSON.parse(storage?.getItem(key+':selected')||legacyStorage?.getItem(key+':selected')||'null'):null;}catch{return null;}},
    selectConversation(id){if(key)for(const source of stores())try{source.setItem(key+':selected',JSON.stringify(id));break;}catch{}},
    clear(){if(key)for(const source of stores())for(const entry of [key,legacyKey])try{source.removeItem(entry);}catch{}},
  };
};
