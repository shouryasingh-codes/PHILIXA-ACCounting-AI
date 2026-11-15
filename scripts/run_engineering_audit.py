import unittest,json,time,sys,argparse
from pathlib import Path
modules='test_purchase_agent test_purchase_conversation test_purchase_memory test_repeat_purchase test_gst_purchase test_chat_gst_purchase test_purchase_drafts test_task_agent_runtime test_task_agent_selection test_task_agent_worker test_day10_recovery test_multi_purchase test_multi_purchase_bridge test_goods_receipt test_receipt_link_service test_intent_router_model test_connector_status test_invoice_extraction'.split()
parser=argparse.ArgumentParser();parser.add_argument('--extended',action='store_true');parser.add_argument('--helper',action='store_true',help='Requires the Windows helper development environment');parser.add_argument('--output',default='regression',choices=['regression','final-regression']);args=parser.parse_args()
if args.extended:modules+='test_engineering_audit test_intent_router test_business_router test_task_agent_evidence test_tally_sync test_tally_customer test_tally_count test_purchase_automation test_posting_authorization test_chat_attachments test_master_creation test_provider_pipeline test_supplier_purchase_read'.split()
if args.helper:modules.append('test_helper_stock_contract')
class Recorded(unittest.TextTestResult):
 def addSuccess(self,test):super().addSuccess(test);records.append({'test':test.id(),'status':'pass'})
 def addFailure(self,test,err):super().addFailure(test,err);records.append({'test':test.id(),'status':'fail','detail':self._exc_info_to_string(err,test)})
 def addError(self,test,err):super().addError(test,err);records.append({'test':test.id(),'status':'error','detail':self._exc_info_to_string(err,test)})
 def addSkip(self,test,reason):super().addSkip(test,reason);records.append({'test':test.id(),'status':'skip','detail':reason})
records=[];start=time.monotonic();suite=unittest.TestLoader().loadTestsFromNames(['scripts.'+m for m in modules]);out=Path('/app/data/engineering-audit');out.mkdir(exist_ok=True)
with (out/(args.output+'.log')).open('w') as log:r=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Recorded).run(suite)
(out/(args.output+'.json')).write_text(json.dumps({'modules':modules,'seconds':time.monotonic()-start,'count':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'tests':records},indent=2))
print('RESULT',r.testsRun,'failures',len(r.failures),'errors',len(r.errors),'skips',len(r.skipped))
sys.exit(0 if r.wasSuccessful() else 1)
