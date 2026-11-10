import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from helper.build_evidence import runtime_ssl_data


def patched_constructor():
    return 'codex-rejected-cas.pem'


class RuntimeResourceTests(unittest.TestCase):
    def test_required_policy_is_collected_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            resource=Path(folder)/'codex-rejected-cas.pem'
            resource.write_bytes(b'synthetic-policy-data')
            fake=SimpleNamespace(__file__=str(Path(folder)/'ssl.py'),
                                 SSLContext=SimpleNamespace(__new__=patched_constructor))
            with patch('helper.build_evidence.ssl',fake): result=runtime_ssl_data()
            self.assertEqual(result[0]['source'],str(resource))
            self.assertEqual(result[0]['sha256'],hashlib.sha256(resource.read_bytes()).hexdigest())
            self.assertEqual(result[0]['destination'],'.')

    def test_missing_policy_blocks_build(self):
        with tempfile.TemporaryDirectory() as folder:
            fake=SimpleNamespace(__file__=str(Path(folder)/'ssl.py'),
                                 SSLContext=SimpleNamespace(__new__=patched_constructor))
            with patch('helper.build_evidence.ssl',fake):
                with self.assertRaisesRegex(RuntimeError,'policy resource missing'): runtime_ssl_data()


if __name__=='__main__': unittest.main()
