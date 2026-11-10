import unittest
from helper.pairing_state import reuse_saved_pairing


class PairingTests(unittest.TestCase):
    def test_offline_same_origin_reuses_saved_credential(self):
        self.assertTrue(reuse_saved_pairing(True,'https://philixa.invalid/','https://philixa.invalid'))

    def test_server_rejection_allows_explicit_new_pairing(self):
        self.assertFalse(reuse_saved_pairing(True,'https://philixa.invalid','https://philixa.invalid',True))

    def test_new_install_or_different_origin_is_not_reused(self):
        self.assertFalse(reuse_saved_pairing(False,'','https://philixa.invalid'))
        self.assertFalse(reuse_saved_pairing(True,'https://a.invalid','https://b.invalid'))


if __name__=='__main__': unittest.main()
