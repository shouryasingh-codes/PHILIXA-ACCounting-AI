import unittest
from app.services.purchase_native_context import history_unit_matches

class UnitAlias(unittest.TestCase):
    def test_singular_bag_matches_exact_native_bags(self):
        self.assertTrue(history_unit_matches('bag','bags','bags'))
    def test_no_cross_unit_or_non_native_alias(self):
        self.assertFalse(history_unit_matches('bag','kg','bags'))
        self.assertFalse(history_unit_matches('bag','bags','kg'))
        self.assertFalse(history_unit_matches('box','boxes','boxes'))
if __name__=='__main__':unittest.main()
