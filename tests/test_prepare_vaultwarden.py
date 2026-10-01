"""Preparation retry/permission checks with disposable files and mocked Docker."""
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare', Path(__file__).parents[1]/'scripts/prepare_vaultwarden.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

class PreparationChecks(unittest.TestCase):
    def test_interrupted_secret_write_reuses_private_password(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); calls=[]; fail=[True]
            def run(*args, **kwargs):
                if args[0]=='ps': return b''
                if 'input' in kwargs:
                    calls.append((args,kwargs))
                    if fail[0]: raise RuntimeError('synthetic interrupted secret write')
                return b''
            output=io.StringIO()
            with patch.object(prepare,'ROOT',root), patch.object(prepare,'run',side_effect=run), \
                 patch.object(prepare.subprocess,'run',return_value=SimpleNamespace(returncode=1)), \
                 patch.object(prepare,'hash_password',return_value='$argon2id$test-only') as hashing, \
                 patch.object(prepare.secrets,'token_urlsafe',return_value='a'*64) as generator, \
                 patch('sys.argv',['prepare_vaultwarden.py','--project','test-vault']), contextlib.redirect_stdout(output):
                old_mask=prepare.os.umask(0o077)
                try:
                    with self.assertRaises(RuntimeError): prepare.main()
                    password_file=root/'data/vaultwarden-access/test-vault-admin-password.txt'
                    self.assertEqual(password_file.stat().st_mode & 0o777,0o600)
                    fail[0]=False
                    prepare.main()
                    self.assertEqual(generator.call_count,1)
                    self.assertEqual(hashing.call_count,2)
                    self.assertEqual(password_file.read_text(),'a'*64+'\n')
                    self.assertIn('mv "$token_tmp"',calls[-1][0][-1])
                    self.assertNotIn('a'*64,output.getvalue())
                    self.assertNotIn('$argon2id$',output.getvalue())
                finally: prepare.os.umask(old_mask)

    def test_insecure_existing_password_file_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); folder=root/'data/vaultwarden-access';folder.mkdir(parents=True)
            password=folder/'test-vault-admin-password.txt';password.write_text('a'*64);password.chmod(0o644)
            with patch.object(prepare,'ROOT',root), patch.object(prepare,'run',return_value=b''), \
                 patch.object(prepare.subprocess,'run',return_value=SimpleNamespace(returncode=1)), \
                 patch.object(prepare,'hash_password') as hashing, patch('sys.argv',['prepare_vaultwarden.py','--project','test-vault']):
                old_mask=prepare.os.umask(0o077)
                try:
                    with self.assertRaisesRegex(RuntimeError,'owner-only'): prepare.main()
                    hashing.assert_not_called()
                finally: prepare.os.umask(old_mask)

if __name__=='__main__': unittest.main(verbosity=2)
