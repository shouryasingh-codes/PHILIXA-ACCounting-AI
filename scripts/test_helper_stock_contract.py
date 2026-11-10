"""Exercise the actual helper wire contract, without Tally/network calls."""
import unittest
from unittest.mock import AsyncMock, patch
from helper.connect import execute_unlocked


class StockContract(unittest.TestCase):
    def job(self, **extra):
        return dict(id='a'*32, operation='stock', company='Test',
                    identity='native-guid', as_of='2026-11-05', **extra)

    def test_all_stock_null_and_omitted_filter_reach_native_reader(self):
        for extra in ({}, {'item_query': None}, {'item_query': 'Cement'}):
            with self.subTest(extra=extra), patch('helper.connect.local_operation', AsyncMock(return_value={'items': []})) as read:
                self.assertEqual(execute_unlocked(self.job(**extra), 9000), {'items': []})
                self.assertEqual(read.call_args.kwargs['item_query'], extra.get('item_query'))

    def test_invalid_filters_never_reach_reader(self):
        for query in ('', '  ', 42, [], 'x'*201):
            with self.subTest(query=query), patch('helper.connect.local_operation', AsyncMock()) as read:
                with self.assertRaises(ValueError): execute_unlocked(self.job(item_query=query), 9000)
                read.assert_not_called()

    def test_required_scope_and_date_still_validated(self):
        for key, value in [('company',None), ('identity',''), ('as_of','not-a-date')]:
            job=self.job(item_query=None); job[key]=value
            with self.subTest(key=key), patch('helper.connect.local_operation', AsyncMock()) as read:
                with self.assertRaises(ValueError): execute_unlocked(job,9000)
                read.assert_not_called()


if __name__ == '__main__': unittest.main()
