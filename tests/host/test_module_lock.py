# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from module_lock import check_modules


class ModuleLockTests(unittest.TestCase):
    def test_checkout_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / 'integration'
            module = workspace / 'dependency'
            root.mkdir()
            module.mkdir()

            def git(*args):
                return subprocess.check_output(['git', '-C', str(module), *args],
                                               stderr=subprocess.STDOUT).decode().strip()

            git('init', '-q')
            source = module / 'source.c'
            source.write_text('original\n')
            git('add', 'source.c')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
            revision = git('rev-parse', 'HEAD')
            lock = {'dependency': revision}
            (root / 'west.yml').write_text(json.dumps({'manifest': {'projects': [
                {'name': 'dependency', 'revision': revision}]}}))
            (root / 'module-lock.json').write_text(json.dumps(lock))
            self.assertEqual(check_modules(root), lock)
            source.write_text('changed\n')
            with self.assertRaisesRegex(ValueError, 'dirty'):
                check_modules(root, lock)
            self.assertEqual(check_modules(root, lock, allow_dirty=('dependency',)), lock)
            with self.assertRaisesRegex(ValueError, 'dirty'):
                check_modules(root, lock, allow_dirty=('another_module',))
            git('add', 'source.c')
            with self.assertRaisesRegex(ValueError, 'dirty'):
                check_modules(root, lock)
            git('restore', '--staged', 'source.c')
            source.write_text('original\n')
            extra = module / 'injected.c'
            extra.write_text('untracked\n')
            with self.assertRaisesRegex(ValueError, 'dirty'):
                check_modules(root, lock)
            extra.unlink()
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-qm', 'moved')
            with self.assertRaisesRegex(ValueError, 'revision'):
                check_modules(root, lock)
            with self.assertRaisesRegex(ValueError, 'revision'):
                check_modules(root, lock, allow_dirty=('dependency',))
