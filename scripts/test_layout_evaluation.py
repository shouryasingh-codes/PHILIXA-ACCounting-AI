import unittest
from scripts.evaluate_invoice_layout import report,equal


class EvaluationTests(unittest.TestCase):
    def test_missing_labels_cannot_pass(self):
        result=report([{'layout_id':str(i),'split':'held_out','result':'/nonexistent','source_sha256':'a'*64} for i in range(10)])
        self.assertFalse(result['pilot_gate_passed'])
        self.assertIsNone(result['held_out_field_exact_match'])

    def test_empty_set_cannot_pass(self):
        self.assertFalse(report([])['pilot_gate_passed'])

    def test_decimal_normalization(self):
        self.assertTrue(equal('1,200.00','1200','amount'))
        self.assertFalse(equal(None,'0','amount'))


if __name__=='__main__':unittest.main()
