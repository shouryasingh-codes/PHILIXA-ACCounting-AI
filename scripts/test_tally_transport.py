"""Isolated transport regressions. No connector executable or Tally calls."""
import asyncio
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch

from app.services.tally_transport import async_client, sync_client, tls_context


class TransportTests(unittest.TestCase):
    def test_missing_debug_log_directory_does_not_break_clients(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = str(Path(folder)/'missing'/'debug-keys.log')
            with patch.dict('os.environ', {'SSLKEYLOGFILE':missing}):
                # Reproduce the same exception type independently of the CA file.
                with self.assertRaises(FileNotFoundError): ssl.create_default_context()
                with sync_client(timeout=1): pass
                async def probe():
                    async with async_client(timeout=1): pass
                asyncio.run(probe())
                context=tls_context()
                self.assertTrue(context.check_hostname)
                self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
                self.assertIsNone(context.keylog_filename)
            self.assertFalse(Path(missing).exists())

    def test_missing_packaged_ca_is_explicit(self):
        with patch('app.services.tally_transport.ca_path', return_value=Path('no-such-ca.pem')):
            with self.assertRaisesRegex(FileNotFoundError,'CA resource missing'): sync_client()

    def test_verification_cannot_be_overridden(self):
        for factory in (sync_client,async_client):
            with self.assertRaises(ValueError): factory(verify=False)
            with self.assertRaises(ValueError): factory(trust_env=True)


if __name__=='__main__': unittest.main()
