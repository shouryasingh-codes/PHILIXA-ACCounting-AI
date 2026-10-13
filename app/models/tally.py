"""Workspace Tally configuration and durable, session-scoped write approvals."""
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, JSON, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base


class TallyDevice(Base):
    __tablename__ = 'tally_devices'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), unique=True)
    credential_hash: Mapped[str] = mapped_column(String(64))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class TallyReadCompany(Base):
    __tablename__ = 'tally_read_companies'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey('tally_devices.id'), nullable=True)
    identity: Mapped[str] = mapped_column(String(250))
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    member_ids: Mapped[list] = mapped_column(JSON, default=list)
    refresh_requested: Mapped[bool] = mapped_column(Boolean, default=True, server_default='true')


class TallyConnection(Base):
    __tablename__ = 'tally_connections'
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True)
    company: Mapped[str] = mapped_column(String(200))
    godown: Mapped[str] = mapped_column(String(200))
    purchase_ledger: Mapped[str] = mapped_column(String(200))
    sales_ledger: Mapped[str] = mapped_column(String(200))
    test_company: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)


class TallyAction(Base):
    __tablename__ = 'tally_actions'
    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[str] = mapped_column(String(100))
    session_id: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    connection_version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    xml_payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='preview')
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey('tally_read_companies.id'), nullable=True)
    device_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    backend: Mapped[str] = mapped_column(String(20), default='python', server_default='python')
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    approved_arguments: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    target_identity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    preconditions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verification_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TallySnapshot(Base):
    __tablename__ = 'tally_snapshots'
    company_id: Mapped[str] = mapped_column(ForeignKey('tally_read_companies.id', ondelete='CASCADE'), primary_key=True)
    generation: Mapped[str] = mapped_column(String(64))
    identity: Mapped[str] = mapped_column(String(250))
    device_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    as_of: Mapped[str] = mapped_column(String(10))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    catalog: Mapped[dict] = mapped_column(JSON)
    items: Mapped[list] = mapped_column(JSON)


class TallyCustomerLink(Base):
    """Verified native ledger identity; never an inferred name-only connection."""
    __tablename__ = 'tally_customer_links'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey('clients.id', ondelete='CASCADE'))
    company_id: Mapped[str] = mapped_column(ForeignKey('tally_read_companies.id', ondelete='CASCADE'))
    company_identity: Mapped[str] = mapped_column(String(250))
    ledger_guid: Mapped[str] = mapped_column(String(250))
    ledger_name: Mapped[str] = mapped_column(String(200))
    ledger_parent: Mapped[str] = mapped_column(String(200))
    action_id: Mapped[str] = mapped_column(ForeignKey('tally_actions.token'))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint('company_id', 'ledger_guid', name='uq_customer_native_ledger'),
        UniqueConstraint('company_id', 'client_id', name='uq_customer_company_link'),
    )


class PurchaseTaxProfile(Base):
    __tablename__='purchase_tax_profiles'
    company_id: Mapped[str]=mapped_column(ForeignKey('tally_read_companies.id',ondelete='CASCADE'),primary_key=True)
    data: Mapped[dict]=mapped_column(JSON)
    revision: Mapped[int]=mapped_column(Integer,default=0)
