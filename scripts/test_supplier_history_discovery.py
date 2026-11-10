import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from xml.etree.ElementTree import fromstring
from app.services import purchase_native_context as native

class Discovery(unittest.IsolatedAsyncioTestCase):
    def ready(self,rate=None):
        return {'status':'ready','complete':True,'suggestions':[] if rate is None else [
            {'field':'0:rate','value':rate,'entry_date':'2026-10-02','requires_confirmation':True}]}

    async def test_unique_supplier_suggestion_does_not_edit_draft(self):
        row=SimpleNamespace(id='d',company_id='c',content={'lines':[{'item_name':'Cement','unit':'bags','rate':None}]})
        before=copy.deepcopy(row.content)
        catalog={'ledgers':[fromstring(f'<LEDGER NAME="{s}"><PARENT>Sundry Creditors</PARENT></LEDGER>') for s in ['A','B']]}
        with patch.object(native,'context',AsyncMock(side_effect=[self.ready('350'),self.ready()])) as read:
            result=await native.conversation_history(None,None,row,catalog)
        self.assertEqual(result['supplier_suggestion']['supplier'],'A')
        self.assertTrue(result['supplier_suggestion']['requires_confirmation'])
        self.assertEqual(row.content,before)
        self.assertEqual(read.await_count,2)

    def test_conflict_incomplete_and_empty_abstain(self):
        for results in [[],[('A',self.ready())],
            [('A',self.ready('350')),('B',self.ready('350'))],
            [('A',self.ready('350')),('B',{'status':'stale','complete':False})],
            [('A',self.ready('350')),('B',{'status':'ready','complete':False})]]:
            self.assertIsNone(native.choose_supplier_suggestion(results))
        conflict=self.ready();conflict['matching_history']=True
        self.assertIsNone(native.choose_supplier_suggestion([('A',self.ready('350')),('B',conflict)]))

    async def test_explicit_rate_and_large_supplier_scope_do_not_scan(self):
        row=SimpleNamespace(id='d',company_id='c',content={'lines':[{'rate':'399'}]})
        catalog={'ledgers':[fromstring(f'<LEDGER NAME="{s}"><PARENT>Sundry Creditors</PARENT></LEDGER>') for s in ['A','B']]}
        with patch.object(native,'context',AsyncMock()) as read:
            await native.conversation_history(None,None,row,catalog)
            row.content['lines'][0]['rate']=None
            catalog['ledgers']*=2
            await native.conversation_history(None,None,row,catalog)
            read.assert_not_awaited()
        self.assertIsNone(row.content['lines'][0]['rate'])

if __name__=='__main__':unittest.main()
