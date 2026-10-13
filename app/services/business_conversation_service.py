"""Scoped transcript storage. Saved UI data never authorizes accounting writes."""
import copy
import json
import secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from app.models.business_conversation import BusinessConversation


class ChatMessage(BaseModel):
    role: Literal['user','assistant']
    text: str = Field(max_length=100000)
    data: dict | None = None
    originalText: str | None = Field(default=None,max_length=4000)


class ConversationSave(BaseModel):
    revision: int = Field(ge=0)
    messages: list[ChatMessage] = Field(max_length=300)

    @model_validator(mode='after')
    def bounded_snapshot(self):
        if len(json.dumps(self.model_dump(),ensure_ascii=False).encode('utf-8')) > 2500000:
            raise ValueError('Chat snapshot too large')
        return self


class ConversationCreate(BaseModel):
    organization_id: str


async def scoped_conversation(db,principal,conversation_id,lock=False):
    query=select(BusinessConversation).where(BusinessConversation.id==conversation_id,
        BusinessConversation.organization_id==principal.organization_id,BusinessConversation.user_id==principal.user_id)
    if lock:query=query.with_for_update().execution_options(populate_existing=True)
    row=await db.scalar(query)
    if row is None:raise HTTPException(404,'Chat nahi mili.')
    return row


def summary(row):
    return {'id':row.id,'title':row.title,'revision':row.revision,'updated_at':row.updated_at.isoformat()}


async def list_conversations(db,principal):
    rows=await db.scalars(select(BusinessConversation).where(BusinessConversation.organization_id==principal.organization_id,
        BusinessConversation.user_id==principal.user_id).order_by(BusinessConversation.updated_at.desc(),BusinessConversation.id.desc()).limit(100))
    return {'conversations':[summary(row) for row in rows]}


async def create_conversation(db,principal,request):
    if request.organization_id!=principal.organization_id:raise HTTPException(409,'Workspace changed; reopen chat.')
    stamp=datetime.now(timezone.utc)
    row=BusinessConversation(id=secrets.token_hex(16),organization_id=principal.organization_id,user_id=principal.user_id,
        title='New chat',messages=[],session_id=principal.session_id,revision=0,created_at=stamp,updated_at=stamp)
    db.add(row);await db.commit()
    return summary(row)


async def read_conversation(db,principal,conversation_id):
    row=await scoped_conversation(db,principal,conversation_id)
    messages=copy.deepcopy(row.messages)
    if row.session_id!=principal.session_id:
        for message in messages:
            if message.get('data',{}).get('preview'):
                message['data']['preview'].update(can_confirm=False,
                    blockers=['Ye preview pichhli login session ka hai. Naya preview banayein.'])
    return {**summary(row),'messages':messages}


async def save_conversation(db,principal,conversation_id,request):
    row=await scoped_conversation(db,principal,conversation_id,lock=True)
    if row.revision!=request.revision:raise HTTPException(409,'Chat doosre tab mein badli hai. Dobara kholein.')
    row.messages=[message.model_dump(exclude_none=True) for message in request.messages]
    row.title=next((message.text.strip()[:100] for message in request.messages if message.role=='user' and message.text.strip()),'New chat')
    row.session_id=principal.session_id
    row.revision+=1;row.updated_at=datetime.now(timezone.utc)
    await db.commit()
    return summary(row)
