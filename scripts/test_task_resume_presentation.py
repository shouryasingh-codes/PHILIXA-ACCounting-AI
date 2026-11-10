import unittest
from types import SimpleNamespace
from datetime import datetime,timezone
from app.services.task_agent_service import view

class Presentation(unittest.TestCase):
    def test_stock_read_intent_does_not_include_stock_changes(self):
        from app.services.task_agent_service import stock_read_question
        self.assertTrue(stock_read_question('stock kitna hai'))
        self.assertTrue(stock_read_question('Cement stock check karo'))
        self.assertTrue(stock_read_question('सभी सामान का स्टॉक बताओ'))
        self.assertTrue(stock_read_question('Please show inventory quantities for every product'))
        self.assertFalse(stock_read_question('stock add karo'))
        self.assertFalse(stock_read_question('स्टॉक घटा दो'))
        self.assertFalse(stock_read_question('purchase entry stock check karo'))
    def test_saved_stock_result_keeps_age_and_does_not_show_purchase_error(self):
        data={'response':'Tally stock: Cement 30 bags. Last synced: 13:39; timeout',
              'stock_results':[{'status':'all','data_source':'saved'}],'data_source':'saved'}
        row=SimpleNamespace(id='x',revision=0,status='needs_input',company_id='company',
            updated_at=datetime.now(timezone.utc),state={'outcome':'answer',
            'summary':'Task saved; requested outcome is not yet verified.',
            'observations':[{'data':data}]})
        self.assertEqual(view(row)['response'],data['response'])
        row.status='completed'
        self.assertEqual(view(row)['response'],data['response'])
    def test_current_domain_question_overrides_generic_missing_rate_list(self):
        data={'response':'Bill pending hai. Maal mil chuka hai ya abhi aana hai?',
              'purchase_assistant':{'field':'message'},'proposal':{'content':{'lines':[{'rate':'350'}]}},
              'issues':[]}
        row=SimpleNamespace(id='x',revision=2,status='needs_input',company_id='company',
            updated_at=datetime.now(timezone.utc),state={'summary':'Need rate, GST, invoice number',
            'issues':[{'message':'old missing fields'}],'observations':[{'data':data}]})
        result=view(row)
        self.assertEqual(result['response'],data['response'])
        self.assertEqual(result['proposal']['content']['lines'][0]['rate'],'350')

if __name__=='__main__':unittest.main()
