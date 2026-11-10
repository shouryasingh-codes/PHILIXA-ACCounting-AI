"""Explicit synthetic release gates. No discovery of live/setup scripts."""
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import time
import unittest

GROUPS={
    'chat':['test_business_context','test_business_graph','test_business_conversations','test_business_voice'],
    'stock':['test_tally_reads','test_tally_suppliers','test_supplier_codec'],
    'purchase':['test_tally','test_tally_sync','test_multi_purchase','test_multi_purchase_bridge','test_gst_purchase','test_gst_native_exports','test_purchase_drafts','test_purchase_review','test_purchase_memory','test_purchase_memory_bridge','test_purchase_automation','test_mcp_write_validation','test_mcp_drafts','test_mcp_business','test_mcp_reports'],
    'count':['test_tally_count'],
    'customer':['test_tally_customer'],
    'connector':['test_connector_status'],
    'extraction':['test_uploaded_invoice_regression','test_local_invoice_ocr','test_extraction_evidence_fixes','test_invoice_transport','test_invoice_extraction','test_bill_documents','test_bill_evaluation'],
    'source_edge_cases':['test_release_fixture_matrix'],
    'posting_authorization':['test_posting_authorization'],
    'launch_defaults':['test_launch_defaults'],
    'invoice_ai_limits':['test_invoice_ai_limits'],
    'practice_pdf_layout':['test_practice_pdf_layout'],
}


def source_fingerprint():
    files=sorted(Path('app').rglob('*.py'))+sorted(Path('scripts').glob('*.py'))
    return hashlib.sha256('\n'.join(str(p)+':'+hashlib.sha256(p.read_bytes()).hexdigest() for p in files).encode()).hexdigest()


def main():
    root=Path('data/release-gates');root.mkdir(parents=True,exist_ok=True)
    report={'run_at':datetime.now(timezone.utc).isoformat(),'source_sha256_before':source_fingerprint(),'scope':'synthetic backend regressions; native Windows lifecycle and browser JS suites run separately','groups':[]}
    with (root/'backend.log').open('w',encoding='utf-8') as log:
        for group,modules in GROUPS.items():
            started=time.monotonic()
            suite=unittest.defaultTestLoader.loadTestsFromNames(['scripts.'+m for m in modules])
            log.write('\n'+group+'\n');log.flush()
            result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
            row={'group':group,'modules':modules,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'successful':result.wasSuccessful() and not result.skipped,'seconds':round(time.monotonic()-started,2)}
            report['groups'].append(row)
            (root/'backend.json').write_text(json.dumps(report,indent=2))
            print(json.dumps(row),flush=True)
    report['source_sha256_after']=source_fingerprint()
    report['source_unchanged']=report['source_sha256_before']==report['source_sha256_after']
    report['passed']=all(r['successful'] for r in report['groups']) and report['source_unchanged']
    report['tests']=sum(r['tests'] for r in report['groups'])
    (root/'backend.json').write_text(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
