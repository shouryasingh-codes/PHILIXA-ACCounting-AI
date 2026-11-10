"""LangGraph async saver backed by the existing PostgreSQL SQLAlchemy engine.

Only JSON graph state is permitted. No pickle, provider objects or credentials.
"""
import json
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple, WRITES_IDX_MAP
from app.models.purchase_agent import PurchaseGraphCheckpoint as CP, PurchaseGraphWrite as Write


class PurchaseSaver(BaseCheckpointSaver):
    def __init__(self,session_factory):
        super().__init__();self.sessions=session_factory

    async def aget_tuple(self,config):
        c=config['configurable'];thread=c['thread_id'];ns=c.get('checkpoint_ns','')
        async with self.sessions() as db:
            stmt=select(CP).where(CP.thread_id==thread,CP.namespace==ns)
            if c.get('checkpoint_id'):stmt=stmt.where(CP.checkpoint_id==c['checkpoint_id'])
            row=await db.scalar(stmt.order_by(CP.checkpoint_id.desc()).limit(1))
            if not row:return None
            writes=(await db.scalars(select(Write).where(Write.thread_id==thread,Write.namespace==ns,
                Write.checkpoint_id==row.checkpoint_id).order_by(Write.task_id,Write.index))).all()
            cfg={'configurable':{'thread_id':thread,'checkpoint_ns':ns,'checkpoint_id':row.checkpoint_id}}
            parent={'configurable':{**cfg['configurable'],'checkpoint_id':row.parent_id}} if row.parent_id else None
            return CheckpointTuple(cfg,row.data,row.metadata_,parent,[(w.task_id,w.channel,w.data['value']) for w in writes])

    async def aput(self,config,checkpoint,metadata,new_versions):
        c=config['configurable'];data=json.loads(json.dumps(checkpoint));meta=json.loads(json.dumps(metadata))
        values=dict(thread_id=c['thread_id'],namespace=c.get('checkpoint_ns',''),checkpoint_id=checkpoint['id'],
                    parent_id=c.get('checkpoint_id'),data=data,metadata=meta)
        async with self.sessions() as db:
            await db.execute(insert(CP.__table__).values(**values).on_conflict_do_nothing());await db.commit()
        return {'configurable':{'thread_id':c['thread_id'],'checkpoint_ns':c.get('checkpoint_ns',''),'checkpoint_id':checkpoint['id']}}

    async def aput_writes(self,config,writes,task_id,task_path=''):
        c=config['configurable']
        async with self.sessions() as db:
            for index,(channel,value) in enumerate(writes):
                if isinstance(value,BaseException):value={'error_type':type(value).__name__}
                data=json.loads(json.dumps({'value':value}))
                stmt=insert(Write).values(thread_id=c['thread_id'],namespace=c.get('checkpoint_ns',''),
                    checkpoint_id=c['checkpoint_id'],task_id=task_id,index=WRITES_IDX_MAP.get(channel,index),channel=channel,data=data)
                await db.execute(stmt.on_conflict_do_nothing())
            await db.commit()

    async def alist(self,config,*,filter=None,before=None,limit=None):
        c=config['configurable']
        async with self.sessions() as db:
            stmt=select(CP.checkpoint_id).where(CP.thread_id==c['thread_id'],CP.namespace==c.get('checkpoint_ns',''))
            if before:stmt=stmt.where(CP.checkpoint_id<before['configurable']['checkpoint_id'])
            ids=(await db.scalars(stmt.order_by(CP.checkpoint_id.desc()).limit(limit or 100))).all()
        for ident in ids:
            value=await self.aget_tuple({'configurable':{**c,'checkpoint_id':ident}})
            if value and (not filter or all(value.metadata.get(k)==v for k,v in filter.items())):yield value
