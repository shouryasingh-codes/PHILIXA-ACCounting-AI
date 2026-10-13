"""Real pgvector tenant/parent/customer/date checks, rolled back; embeddings mocked."""
import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from app.database.session import AsyncSessionLocal
from app.models.organization import Organization
from app.models.organization_membership import OrganizationMembership
from app.models.user import User
from app.models.meeting import Meeting
from app.models.meeting_evidence import MeetingEvidence
from app.models.client import Client
from app.services.semantic_search_service import search_meeting_evidence


async def main():
    suffix=uuid.uuid4().hex
    orgs=['history-a-'+suffix,'history-b-'+suffix]
    users=['history-owner-'+suffix,'history-member-'+suffix]
    vector=[1.0]+[0.0]*1023
    async with AsyncSessionLocal() as db:
        try:
            db.add_all([Organization(id=o,name='History test',slug=o) for o in orgs])
            db.add_all([User(id=u,email=u+'@example.invalid',hashed_password='unused') for u in users])
            await db.flush()
            db.add_all([OrganizationMembership(user_id=u,organization_id=o,role='member') for o in orgs for u in users])
            await db.flush()
            client=Client(organization_id=orgs[0],user_id=users[0],name='History customer')
            db.add(client); await db.flush()
            fixtures=[
                (orgs[0],users[0],date(2026,9,1),client.id),
                (orgs[0],users[1],date(2026,9,2),None),
                (orgs[1],users[0],date(2026,9,3),None),
                (orgs[0],users[0],date(2026,8,1),client.id),
            ]
            meetings=[]
            for org,user,day,cid in fixtures:
                meeting=Meeting(organization_id=org,user_id=user,client_id=cid,meeting_date=day,raw_notes='Synthetic history')
                db.add(meeting); await db.flush(); meetings.append(meeting)
                db.add(MeetingEvidence(organization_id=org,user_id=user,meeting_id=meeting.id,chunk_index=0,chunk_text='Discount requested',embedding=vector))
            # Evidence pretending to belong to this tenant/member, but parent belongs elsewhere.
            for parent in (meetings[1],meetings[2]):
                db.add(MeetingEvidence(organization_id=orgs[0],user_id=users[0],meeting_id=parent.id,chunk_index=1,chunk_text='Cross-parent injection',embedding=vector))
            await db.flush()
            owner=SimpleNamespace(organization_id=orgs[0],user_id=users[0],role='owner')
            member=SimpleNamespace(**{**owner.__dict__,'role':'member'})
            async def search(principal,**kwargs):
                return await search_meeting_evidence(db,'discount',orgs[0],users[0],principal=principal,**kwargs)
            with patch('app.services.semantic_search_service.generate_query_embedding',return_value=vector):
                owned=await search(owner)
                assert {e['meeting_id'] for e in owned}=={meetings[i].id for i in (0,1,3)}
                own=await search(member)
                assert {e['meeting_id'] for e in own}=={meetings[i].id for i in (0,3)}
                scoped=await search(owner,client_id=client.id,start_date=date(2026,9,1),end_date=date(2026,9,30))
                assert [e['meeting_id'] for e in scoped]==[meetings[0].id]
                legacy=await search(None)
                assert {e['meeting_id'] for e in legacy}=={meetings[i].id for i in (0,3)}
                try:
                    await search(SimpleNamespace(organization_id=orgs[1],user_id=users[0],role='owner'))
                except ValueError:
                    pass
                else:
                    raise AssertionError('Wrong principal workspace accepted')
            print('PASS: real pgvector owner/member, evidence AND parent scopes, customer/date and legacy user scope')
        finally:
            await db.rollback()
            print('All history fixtures rolled back; no embedding worker or notifications started')


if __name__=='__main__':
    asyncio.run(main())
