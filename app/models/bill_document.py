"""Private source documents and durable intake state, independent of Tally actions."""
from datetime import datetime
from sqlalchemy import String,Integer,DateTime,ForeignKey,UniqueConstraint,JSON,Boolean
from sqlalchemy.orm import Mapped,mapped_column
from app.database.base import Base


class DocumentBatch(Base):
    __tablename__='document_batches'
    id: Mapped[str]=mapped_column(String(32),primary_key=True)
    organization_id: Mapped[str]=mapped_column(ForeignKey('organizations.id',ondelete='CASCADE'),index=True)
    user_id: Mapped[str]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))


class BillDocument(Base):
    __tablename__='bill_documents'
    __table_args__=(UniqueConstraint('organization_id','user_id','company_id','sha256',name='uq_bill_document_source'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True)
    organization_id: Mapped[str]=mapped_column(ForeignKey('organizations.id',ondelete='CASCADE'),index=True)
    user_id: Mapped[str]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),index=True)
    filename: Mapped[str]=mapped_column(String(160))
    media_type: Mapped[str]=mapped_column(String(40))
    size: Mapped[int]=mapped_column(Integer)
    sha256: Mapped[str]=mapped_column(String(64))
    object_key: Mapped[str]=mapped_column(String(400))
    status: Mapped[str]=mapped_column(String(20),default='queued',index=True)
    extraction_status: Mapped[str|None]=mapped_column(String(30),nullable=True)
    extraction_result: Mapped[dict|None]=mapped_column(JSON,nullable=True)
    extraction_error: Mapped[str|None]=mapped_column(String(500),nullable=True)
    extraction_attempts: Mapped[int]=mapped_column(Integer,default=0,server_default='0')
    extraction_generation: Mapped[int]=mapped_column(Integer,default=0,server_default='0')
    extraction_split: Mapped[bool]=mapped_column(Boolean,default=False,server_default='false')
    extraction_lease_token: Mapped[str|None]=mapped_column(String(32),nullable=True)
    extraction_lease_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    extraction_next_attempt_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    error_code: Mapped[str|None]=mapped_column(String(40),nullable=True)
    page_count: Mapped[int|None]=mapped_column(Integer,nullable=True)
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    generation: Mapped[int]=mapped_column(Integer,default=0)
    lease_token: Mapped[str|None]=mapped_column(String(32),nullable=True)
    lease_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    next_attempt_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))


class DocumentBatchItem(Base):
    __tablename__='document_batch_items'
    batch_id: Mapped[str]=mapped_column(ForeignKey('document_batches.id',ondelete='CASCADE'),primary_key=True)
    document_id: Mapped[str]=mapped_column(ForeignKey('bill_documents.id',ondelete='CASCADE'),primary_key=True)
