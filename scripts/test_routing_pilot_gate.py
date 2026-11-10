import unittest
from scripts.intent_router_pilot_config import eligible

class PilotGateTests(unittest.TestCase):
    def test_current_matching_evidence_is_required(self):
        report={'summary':{'gate_passed':True},'fingerprint':'current'}
        evidence={'evaluation_fingerprint':'current','implementation_sha256':'source','regressions_passed':True,
                  'browser_passed':True,'zero_critical_errors':True}
        self.assertTrue(eligible(report,evidence,'current','source'))
        self.assertFalse(eligible(report,evidence,'changed','source'))
        self.assertFalse(eligible(report,evidence,'current','changed'))
        self.assertFalse(eligible({**report,'summary':{'gate_passed':False}},evidence,'current','source'))
        partial={**evidence,'browser_passed':False,'zero_critical_errors':None}
        self.assertFalse(eligible(report,partial,'current','source'))
        self.assertTrue(eligible(report,partial,'current','source',browser_required=False))

if __name__=='__main__':unittest.main()
