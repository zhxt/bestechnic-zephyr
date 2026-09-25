# SPDX-License-Identifier: Apache-2.0
"""Exercise downloaded HAL libraries and formal archive provenance."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from hal_blobs import blob_metadata
from package_source import HAL_METADATA, hal_files, repository_state, snapshot


class HalBlobs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'module'
        self.root.mkdir()
        self.output = self.root.parent / 'hal.tar'
        for name in HAL_METADATA:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Fixture metadata\n')
        self.library = 'zephyr/blobs/lib/chip/libhal.a'
        self.lib = self.root / self.library
        self.lib.parent.mkdir(parents=True)
        self.lib.write_bytes(b'!<arch>\nfixture library\n')
        header = self.root / 'include/hal.h'
        header.parent.mkdir()
        header.write_text('/* fixture */\n')
        self.manifest = {'version': 'test-1', 'artifacts': {
            self.library: hashlib.sha256(self.lib.read_bytes()).hexdigest(),
            'include/hal.h': hashlib.sha256(header.read_bytes()).hexdigest()}}
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        self.module = {'name': 'hal_bestechnic', 'blobs': [{
            'path': self.library.removeprefix('zephyr/blobs/'),
            'sha256': self.manifest['artifacts'][self.library], 'type': 'lib',
            'version': 'test-1', 'license-path': 'THIRD_PARTY_NOTICES.md',
            'url': 'https://example.invalid/releases/test-1/libhal.a',
            'description': 'Fixture library', 'size': self.lib.stat().st_size}]}
        self.save_module()
        (self.root / '.gitignore').write_text('/zephyr/blobs/lib/\n')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'test fixture')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args],
                                       stderr=subprocess.STDOUT)

    def save_module(self):
        (self.root / 'zephyr/module.yml').write_text(yaml.safe_dump(self.module))

    def test_downloaded_library_is_clean_and_in_formal_archive(self):
        self.assertFalse(repository_state(self.root)['dirty'])
        self.assertEqual(self.git('ls-files', '--', self.library), b'')
        report = snapshot(self.root, self.output, 'hal', formal=True)
        self.assertEqual(report['blobs'][self.library]['sha256'],
                         self.manifest['artifacts'][self.library])
        with tarfile.open(self.output) as archive:
            self.assertEqual(set(archive.getnames()), set(hal_files(self.root)))
            self.assertEqual(archive.extractfile(self.library).read(), self.lib.read_bytes())
        first = self.output.read_bytes()
        snapshot(self.root, self.output, 'hal', formal=True)
        self.assertEqual(first, self.output.read_bytes())

    def test_missing_and_corrupt_downloads_are_rejected(self):
        self.lib.unlink()
        with self.assertRaisesRegex(ValueError, 'west blobs fetch hal_bestechnic'):
            hal_files(self.root)
        self.lib.write_bytes(b'<html>sign in</html>')
        self.assertFalse(repository_state(self.root)['dirty'])
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            snapshot(self.root, self.output, 'hal', formal=True)
        self.assertFalse(self.output.exists())

    def test_git_tracked_library_is_rejected(self):
        self.git('add', '-f', self.library)
        with self.assertRaisesRegex(ValueError, 'must not be tracked'):
            hal_files(self.root)

    def test_blob_list_must_cover_manifest_libraries_once(self):
        original = self.module['blobs'][0]
        for entries in ([], [original, original], [{**original, 'path': 'lib/extra.a'}]):
            with self.subTest(entries=entries):
                self.module['blobs'] = entries
                self.save_module()
                with self.assertRaises(ValueError):
                    blob_metadata(self.root)

    def test_blob_hash_version_type_and_size_are_checked(self):
        original = dict(self.module['blobs'][0])
        for key, value in (('sha256', '0' * 64), ('version', 'test-2'),
                           ('type', 'img'), ('size', 1)):
            with self.subTest(key=key):
                self.module['blobs'][0] = {**original, key: value}
                self.save_module()
                with self.assertRaises(ValueError):
                    hal_files(self.root)

    def test_paths_and_licenses_cannot_escape_module(self):
        original = dict(self.module['blobs'][0])
        for key, value in (('path', '../outside.a'), ('path', '/tmp/outside.a'),
                           ('license-path', '../LICENSE'), ('license-path', 'missing.txt')):
            with self.subTest(key=key, value=value):
                self.module['blobs'][0] = {**original, key: value}
                self.save_module()
                with self.assertRaises(ValueError):
                    blob_metadata(self.root)

    def test_blob_symlink_is_rejected(self):
        outside = self.root.parent / 'library.a'
        self.lib.rename(outside)
        self.lib.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            hal_files(self.root)

    def test_url_requires_http_without_embedded_credentials(self):
        for url in ('file:///tmp/lib.a', 'https://user:secret@example.invalid/lib.a', ''):
            with self.subTest(url=url):
                self.module['blobs'][0]['url'] = url
                self.save_module()
                with self.assertRaises(ValueError):
                    blob_metadata(self.root)

    def test_changed_git_metadata_rejects_formal_archive(self):
        (self.root / 'README.md').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'unchanged clean commit'):
            snapshot(self.root, self.output, 'hal', formal=True)

    def test_download_modified_during_archive_is_rejected(self):
        check_output = subprocess.check_output

        def mutate_after_git_archive(command, **kwargs):
            result = check_output(command, **kwargs)
            if 'archive' in command:
                self.lib.write_bytes(b'changed during archive')
            return result

        with patch('package_source.subprocess.check_output', side_effect=mutate_after_git_archive):
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                snapshot(self.root, self.output, 'hal', formal=True)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
