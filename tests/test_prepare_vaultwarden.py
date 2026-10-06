"""Preparation retry/permission checks with disposable files and mocked Docker."""
import contextlib
import importlib.util
import io
import hashlib
import shutil
import sqlite3
import ssl
import subprocess
import tarfile
import time
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
                 patch.object(prepare,'prepare_storage',return_value=root/'data/vaultwarden'), \
                 patch.object(prepare,'prepare_tls'), \
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

    def test_failure_after_data_copy_does_not_restart_a_diverging_legacy_vault(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);calls=[]
            def run(*args,**kwargs):
                calls.append(args)
                if args[0]=='ps':return b'test-vault-container\n'
                if args[0]=='run' and any('chown -R' in str(arg) for arg in args):
                    raise RuntimeError('synthetic post-copy ownership failure')
                return b''
            def copy(project,destination):
                destination=Path(destination);destination.mkdir(parents=True)
                (destination/'db.sqlite3').write_bytes(b'synthetic completed migration')
                return destination
            with patch.object(prepare,'ROOT',root), patch.object(prepare,'run',side_effect=run), \
                 patch.object(prepare,'prepare_storage',side_effect=copy), patch.object(prepare,'prepare_tls'), \
                 patch.object(prepare.subprocess,'run',return_value=SimpleNamespace(returncode=0)), \
                 patch('sys.argv',['prepare_vaultwarden.py','--project','test-vault']), contextlib.redirect_stdout(io.StringIO()):
                old_mask=prepare.os.umask(0o077)
                try:
                    with self.assertRaisesRegex(RuntimeError,'post-copy'):
                        prepare.main()
                finally:prepare.os.umask(old_mask)
            self.assertIn(('stop','test-vault-container'),calls)
            self.assertNotIn(('start','test-vault-container'),calls,
                'Restarting the legacy volume after migration permits writes missing from the new bind snapshot')
            self.assertEqual((root/'data/vaultwarden/db.sqlite3').read_bytes(),b'synthetic completed migration')

    def test_insecure_existing_password_file_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); folder=root/'data/vaultwarden-access';folder.mkdir(parents=True)
            password=folder/'test-vault-admin-password.txt';password.write_text('a'*64);password.chmod(0o644)
            with patch.object(prepare,'ROOT',root), patch.object(prepare,'run',return_value=b''), \
                 patch.object(prepare,'prepare_storage',return_value=root/'data/vaultwarden'), \
                 patch.object(prepare,'prepare_tls'), \
                 patch.object(prepare.subprocess,'run',return_value=SimpleNamespace(returncode=1)), \
                 patch.object(prepare,'hash_password') as hashing, patch('sys.argv',['prepare_vaultwarden.py','--project','test-vault']):
                old_mask=prepare.os.umask(0o077)
                try:
                    with self.assertRaisesRegex(RuntimeError,'owner-only'): prepare.main()
                    hashing.assert_not_called()
                finally: prepare.os.umask(old_mask)

def vault_archive(entries):
    """An in-memory tar from synthetic files, never a user's volume."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name, contents, kind in entries:
            member = tarfile.TarInfo(name)
            member.mode = 0o600
            member.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                member.linkname = '../outside'
            if kind == tarfile.REGTYPE:
                member.size = len(contents)
                archive.addfile(member, io.BytesIO(contents))
            else:
                archive.addfile(member)
    return output.getvalue()


def sqlite_bytes(directory):
    path = directory / 'fixture.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE fixture (value TEXT NOT NULL)')
        db.execute('INSERT INTO fixture VALUES (?)', ('synthetic vault record',))
    contents = path.read_bytes()
    path.unlink()
    return contents


class StorageMigrationChecks(unittest.TestCase):
    def mock_docker(self, archive, *, legacy=True, fail_backup=False):
        calls = []
        def invoke(args, **kwargs):
            self.assertEqual(args[0], 'docker', 'Migration must not execute arbitrary commands')
            calls.append(args)
            if args[1:3] == ['volume', 'inspect']:
                return SimpleNamespace(returncode=0 if legacy else 1)
            self.assertEqual(args[1], 'run')
            self.assertIn('--read-only', args)
            self.assertIn('none', args)
            self.assertIn('--mount', args)
            mount = args[args.index('--mount') + 1]
            self.assertIn('dst=/backup,readonly', mount)
            kwargs['stdout'].write(archive)
            return SimpleNamespace(returncode=1 if fail_backup else 0)
        return invoke, calls

    def test_nested_files_and_real_sqlite_migrate_from_volume_root_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = sqlite_bytes(root)
            archive = vault_archive([
                ('.', b'', tarfile.DIRTYPE),
                ('./db.sqlite3', db, tarfile.REGTYPE),
                ('./attachments/group/blob', b'synthetic attachment', tarfile.REGTYPE),
                ('./rsa_key.pem', b'synthetic non-secret test key', tarfile.REGTYPE),
            ])
            invoke, calls = self.mock_docker(archive)
            with patch.object(prepare, 'ROOT', root), patch.object(prepare.subprocess, 'run', side_effect=invoke), contextlib.redirect_stdout(io.StringIO()):
                destination = prepare.prepare_storage('test-vault', root/'data/vaultwarden')
            self.assertEqual((destination/'db.sqlite3').read_bytes(), db)
            self.assertEqual((destination/'attachments/group/blob').read_bytes(), b'synthetic attachment')
            with sqlite3.connect(destination/'db.sqlite3') as conn:
                self.assertEqual(conn.execute('SELECT value FROM fixture').fetchone()[0], 'synthetic vault record')
            self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
            self.assertEqual((destination/'rsa_key.pem').stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(destination.parent.glob('.vault-migrate-*')), [])
            backups = list((root/'backups/vaultwarden').glob('*.tar'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), archive)
            self.assertEqual(calls[-1][calls[-1].index('--mount')+1], 'type=volume,src=test-vault_vaultwarden-data,dst=/backup,readonly')

    def test_populated_destination_is_backed_up_but_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); destination = root/'data/vaultwarden'
            destination.mkdir(parents=True)
            original = sqlite_bytes(root)
            (destination/'db.sqlite3').write_bytes(original)
            (destination/'existing-file').write_bytes(b'keep this exact data')
            archive = vault_archive([('legacy-only', b'do not replace populated bind data', tarfile.REGTYPE)])
            invoke, calls = self.mock_docker(archive)
            with patch.object(prepare, 'ROOT', root), patch.object(prepare.subprocess, 'run', side_effect=invoke), contextlib.redirect_stdout(io.StringIO()):
                prepare.prepare_storage('test-vault', destination)
            self.assertEqual((destination/'db.sqlite3').read_bytes(), original)
            self.assertEqual((destination/'existing-file').read_bytes(), b'keep this exact data')
            self.assertFalse((destination/'legacy-only').exists())
            self.assertEqual(calls[-1][calls[-1].index('--mount')+1], f'type=bind,src={destination.resolve()},dst=/backup,readonly')

    def test_traversal_links_and_special_files_are_rejected_without_partial_commit(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/escape', tarfile.REGTYPE),
                           ('attachments/link', tarfile.SYMTYPE), ('hard-link', tarfile.LNKTYPE),
                           ('fifo', tarfile.FIFOTYPE), ('device', tarfile.CHRTYPE)]:
            with self.subTest(path=name, kind=kind), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);destination=root/'data/vaultwarden'
                archive=vault_archive([('normal-file', b'not yet committed', tarfile.REGTYPE), (name,b'bad',kind)])
                invoke,_=self.mock_docker(archive)
                with patch.object(prepare,'ROOT',root), patch.object(prepare.subprocess,'run',side_effect=invoke), contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(RuntimeError,'Unexpected path'):
                        prepare.prepare_storage('test-vault',destination)
                self.assertEqual(list(destination.iterdir()),[])
                self.assertEqual(list(destination.parent.glob('.vault-migrate-*')),[])
                self.assertFalse((root/'data/escape').exists())

    def test_corrupt_database_does_not_commit_and_retry_uses_intact_legacy_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);destination=root/'data/vaultwarden'
            invalid=vault_archive([('db.sqlite3',b'not a SQLite database',tarfile.REGTYPE)])
            invoke,_=self.mock_docker(invalid)
            with patch.object(prepare,'ROOT',root), patch.object(prepare.subprocess,'run',side_effect=invoke), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises((RuntimeError,sqlite3.DatabaseError)):
                    prepare.prepare_storage('test-vault',destination)
            self.assertEqual(list(destination.iterdir()),[])
            self.assertEqual(list(destination.parent.glob('.vault-migrate-*')),[])
            valid=vault_archive([('db.sqlite3',sqlite_bytes(root),tarfile.REGTYPE)])
            invoke,_=self.mock_docker(valid)
            with patch.object(prepare,'ROOT',root), patch.object(prepare.subprocess,'run',side_effect=invoke), contextlib.redirect_stdout(io.StringIO()):
                prepare.prepare_storage('test-vault',destination)
            with sqlite3.connect(destination/'db.sqlite3') as conn:
                self.assertEqual(conn.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertEqual(len(list((root/'backups/vaultwarden').glob('*.tar'))),2)

    def test_backup_failure_preserves_empty_destination_and_legacy_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);destination=root/'data/vaultwarden'
            invoke,calls=self.mock_docker(b'incomplete archive',fail_backup=True)
            with patch.object(prepare,'ROOT',root), patch.object(prepare.subprocess,'run',side_effect=invoke):
                with self.assertRaisesRegex(RuntimeError,'backup failed'):
                    prepare.prepare_storage('test-vault',destination)
            self.assertEqual(list(destination.iterdir()),[])
            self.assertTrue(all('rm' not in call and 'stop' not in call for call in calls))

    def test_fresh_install_creates_private_empty_bind_without_accessing_volumes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);invoke,calls=self.mock_docker(b'',legacy=False)
            with patch.object(prepare,'ROOT',root), patch.object(prepare.subprocess,'run',side_effect=invoke):
                destination=prepare.prepare_storage('test-vault',root/'data/vaultwarden')
            self.assertEqual(destination.stat().st_mode & 0o777,0o700)
            self.assertEqual(list(destination.iterdir()),[])
            self.assertEqual(len(calls),1)

    def test_symlink_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);actual=root/'outside';actual.mkdir();link=root/'vault';link.symlink_to(actual,target_is_directory=True)
            with patch.object(prepare.subprocess,'run') as docker:
                with self.assertRaisesRegex(RuntimeError,'symbolic link'):
                    prepare.prepare_storage('test-vault',link)
                docker.assert_not_called()


@unittest.skipUnless(shutil.which('openssl'), 'openssl is required for disposable certificate checks')
class TLSPreparationChecks(unittest.TestCase):
    def prepare(self, directory):
        with contextlib.redirect_stdout(io.StringIO()):
            return prepare.prepare_tls(directory)

    def fingerprint(self, directory):
        return tuple(hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in ('cert.pem','key.pem'))

    def test_generate_and_reuse_with_system_openssl_preserves_key_and_required_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'tls'
            self.prepare(directory)
            first=self.fingerprint(directory)
            decoded=ssl._ssl._test_decode_cert(str(directory/'cert.pem'))
            names=set(decoded['subjectAltName'])
            self.assertTrue({('DNS','localhost'),('DNS','vaultwarden'),('IP Address','127.0.0.1')}<=names)
            text=subprocess.run(['openssl','x509','-in',str(directory/'cert.pem'),'-noout','-text'],check=True,capture_output=True,text=True).stdout
            self.assertIn('CA:FALSE',text)
            ssl.create_default_context().load_cert_chain(str(directory/'cert.pem'),str(directory/'key.pem'))
            self.prepare(directory)
            self.assertEqual(self.fingerprint(directory),first,'Preparation must not rotate a valid existing certificate/key')
            self.assertEqual(directory.stat().st_mode & 0o777,0o700)
            self.assertEqual((directory/'key.pem').stat().st_mode & 0o777,0o644)

    def test_existing_mismatched_key_is_rejected_without_replacing_either_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);first=root/'first';other=root/'other'
            self.prepare(first);self.prepare(other)
            (first/'key.pem').write_bytes((other/'key.pem').read_bytes())
            before=self.fingerprint(first)
            with self.assertRaisesRegex(RuntimeError,'do not match'):
                self.prepare(first)
            self.assertEqual(self.fingerprint(first),before)

    def test_wrong_hostnames_expiration_and_future_validity_require_deliberate_renewal(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'tls';self.prepare(directory)
            before=self.fingerprint(directory)
            original=ssl._ssl._test_decode_cert(str(directory/'cert.pem'))
            cases=[{**original,'subjectAltName':(('DNS','localhost'),)},
                   {**original,'notAfter':'Jan  1 00:00:00 2000 GMT'},
                   {**original,'notBefore':'Jan  1 00:00:00 2099 GMT'}]
            for decoded in cases:
                with self.subTest(decoded=decoded), patch.object(prepare.ssl._ssl,'_test_decode_cert',return_value=decoded):
                    with self.assertRaisesRegex(RuntimeError,'renewal|required hostnames'):
                        self.prepare(directory)
                self.assertEqual(self.fingerprint(directory),before)

    def test_certificate_authority_is_rejected_as_server_leaf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'tls';directory.mkdir()
            config=root/'openssl.cnf'
            config.write_text('[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=leaf\n'
                '[dn]\nCN=Disposable test CA\n[leaf]\nbasicConstraints=critical,CA:TRUE\n'
                'keyUsage=critical,keyCertSign,cRLSign\n'
                'subjectAltName=DNS:localhost,DNS:vaultwarden,IP:127.0.0.1\n')
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','365','-sha256',
                '-keyout',str(directory/'key.pem'),'-out',str(directory/'cert.pem'),'-config',str(config)],
                check=True,capture_output=True,timeout=20)
            before=self.fingerprint(directory)
            with self.assertRaisesRegex(RuntimeError,'server leaf'):
                self.prepare(directory)
            self.assertEqual(self.fingerprint(directory),before)

    def test_encrypted_key_fails_without_prompt_or_rotation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'tls';self.prepare(directory)
            encrypted=directory/'encrypted.pem'
            subprocess.run(['openssl','pkey','-in',str(directory/'key.pem'),'-aes256',
                '-passout','pass:disposable-test-only','-out',str(encrypted)],
                check=True,capture_output=True,timeout=20)
            encrypted.replace(directory/'key.pem')
            before=self.fingerprint(directory);started=time.monotonic()
            with self.assertRaises((RuntimeError,subprocess.CalledProcessError)):
                self.prepare(directory)
            self.assertLess(time.monotonic()-started,10)
            self.assertEqual(self.fingerprint(directory),before)

    def test_incomplete_pair_is_rejected_without_rotation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'tls';self.prepare(directory)
            key=(directory/'key.pem').read_bytes();(directory/'cert.pem').unlink()
            with self.assertRaisesRegex(RuntimeError,'incomplete'):
                self.prepare(directory)
            self.assertEqual((directory/'key.pem').read_bytes(),key)
            self.assertFalse((directory/'cert.pem').exists())

    def test_dangling_certificate_symlink_is_rejected_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'tls';directory.mkdir()
            cert=directory/'cert.pem';cert.symlink_to(directory/'missing')
            with self.assertRaisesRegex(RuntimeError,'unsafe|incomplete'):
                self.prepare(directory)
            self.assertTrue(cert.is_symlink())
            self.assertFalse((directory/'key.pem').exists())

if __name__=='__main__': unittest.main(verbosity=2)
