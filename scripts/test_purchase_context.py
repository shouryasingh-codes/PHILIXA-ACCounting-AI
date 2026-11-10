import unittest
from datetime import date
from types import SimpleNamespace
from app.services.purchase_context import rate_evidence, pending_fields


class Evidence(unittest.TestCase):
    def content(self, **changes):
        return dict(party_name='Supplier', lines=[dict(item_name='Cement', unit='bags', rate=None)], **changes)

    def row(self, rate='350', stamp='2026-10-01', **changes):
        content = dict(party_name='Supplier', entry_date=stamp, invoice_number='OLD-1',
                       lines=[dict(item_name='Cement', unit='bags', rate=rate)])
        content.update(changes)
        return SimpleNamespace(id='old', content=content)

    def test_exact_historical_rate_is_only_a_suggestion(self):
        content = self.content()
        result = rate_evidence(content, [self.row()], date(2026, 10, 28))
        self.assertEqual(result[0]['value'], '350')
        self.assertTrue(result[0]['requires_confirmation'])
        self.assertIsNone(content['lines'][0]['rate'])

    def test_ambiguous_stale_future_wrong_party_and_unit_abstain(self):
        today = date(2026, 10, 28)
        cases = [[self.row(), self.row('360')], [self.row(stamp='2025-01-01')],
                 [self.row(stamp='2026-11-01')], [self.row(party_name='Other')],
                 [self.row(lines=[dict(item_name='Cement', unit='kg', rate='350')])],
                 [self.row(lines=[dict(item_name='Cement', unit='bags', rate='350')]*2)],
                 [self.row(rate='NaN')]]
        for rows in cases:
            with self.subTest(rows=rows):
                self.assertEqual(rate_evidence(self.content(), rows, today), [])

    def test_explicit_price_preserved_and_transaction_date_bounds_history(self):
        content = self.content(entry_date='2026-09-01')
        self.assertEqual(rate_evidence(content, [self.row()], date(2026, 10, 28)), [])
        content['lines'][0]['rate'] = '399'
        self.assertEqual(rate_evidence(content, [self.row(stamp='2026-08-01')], date(2026, 10, 28)), [])

    def test_zero_tax_is_present_not_missing(self):
        content = self.content(tax_treatment='regular_domestic_goods')
        content['lines'][0].update(gst_rate='0', taxable_amount='0')
        missing = pending_fields(content)
        self.assertNotIn('0:gst_rate', missing)
        self.assertIn('invoice_number', missing)


if __name__ == '__main__':
    unittest.main()
