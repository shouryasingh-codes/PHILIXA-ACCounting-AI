"""Unit tests only; do not launch the connector or make network requests."""
import shutil,ssl,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import certifi
from helper.tls import configure_bundled_ca

class BundledTLS(unittest.TestCase):
    def test_packaged_ca_loads_with_certificate_and_hostname_validation(self):
        source=certifi.where()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'certifi'/'cacert.pem'
            target.parent.mkdir();shutil.copyfile(source,target)
            with patch.object(certifi,'where',certifi.where):
                self.assertEqual(configure_bundled_ca(directory),target)
                context=ssl.create_default_context(cafile=certifi.where())
                self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
                self.assertTrue(context.check_hostname)

    def test_missing_bundle_fails_closed(self):
        original=certifi.where
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError,'bundle missing'):configure_bundled_ca(directory)
        self.assertIs(certifi.where,original)

if __name__=='__main__':unittest.main()
