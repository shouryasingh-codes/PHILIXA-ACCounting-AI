import unittest
from app.services.task_agent_evidence import explicit_master_names

class EvidenceTests(unittest.TestCase):
    def test_full_user_name_recovers_omitted_suffix(self):
        content={'party_name':'Philixa GST TEST Supplier','lines':[{'item_name':'Goods18','rate':'100'}]}
        result=explicit_master_names(content,'Philixa GST TEST Supplier Local; Philixa GST TEST Goods18',
            ['Philixa GST TEST Supplier Local','Philixa GST TEST Supplier Interstate'],['Philixa GST TEST Goods18'])
        self.assertEqual(result['party_name'],'Philixa GST TEST Supplier Local')
        self.assertEqual(result['lines'][0]['rate'],'100')
        self.assertEqual(content['party_name'],'Philixa GST TEST Supplier')

    def test_ambiguous_or_absent_source_cannot_choose_identity(self):
        content={'party_name':'Sharma','lines':[]}
        for message in ('Sharma','Sharma Local aur Sharma Interstate'):
            self.assertEqual(explicit_master_names(content,message,['Sharma Local','Sharma Interstate'],[])['party_name'],'Sharma')

    def test_substring_inside_another_word_is_not_evidence(self):
        self.assertEqual(explicit_master_names({'party_name':'ABC','lines':[]},'XABC LocalZ',['ABC Local'],[])['party_name'],'ABC')

if __name__=='__main__':unittest.main()
