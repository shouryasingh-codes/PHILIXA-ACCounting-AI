"""Authoritative chat-to-source links. Transcript JSON is presentation only."""
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class ChatBillMessage(Base):
    __tablename__='chat_bill_messages'
    __table_args__=(UniqueConstraint('organization_id','user_id','request_id'),)
    id:Mapped[str]=mapped_column(String(32),primary_key=True)
    organization_id:Mapped[str]=mapped_column(String(100),index=True)
    user_id:Mapped[str]=mapped_column(String(100),index=True)
    conversation_id:Mapped[str]=mapped_column(ForeignKey('business_conversations.id'),index=True)
    task_id:Mapped[str]=mapped_column(ForeignKey('agent_tasks.id'),unique=True)
    request_id:Mapped[str]=mapped_column(String(64))
    request_hash:Mapped[str]=mapped_column(String(64))
    text:Mapped[str]=mapped_column(String(4000))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))


class ChatBillAttachment(Base):
    __tablename__='chat_bill_attachments'
    __table_args__=(UniqueConstraint('message_id','document_id'),UniqueConstraint('message_id','position'))
    id:Mapped[str]=mapped_column(String(32),primary_key=True)
    message_id:Mapped[str]=mapped_column(ForeignKey('chat_bill_messages.id'),index=True)
    document_id:Mapped[str]=mapped_column(ForeignKey('bill_documents.id'),index=True)
    position:Mapped[int]=mapped_column(Integer)
