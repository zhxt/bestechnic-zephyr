# SPDX-License-Identifier: Apache-2.0
"""Test artifact boundaries rather than a particular directory inventory."""
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from project_files import file_hashes, select_files
from package_source import snapshot
from check_repo import check_links


class ProjectFiles(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'source'
        (self.root / 'scripts').mkdir(parents=True)
        (self.root / 'src').mkdir()
        self.rules = {'schema': 1, 'ignored_directories': ['.git', '__pycache__', 'build'],
                      'ignored_names': ['*.swp', '*~', '.env'], 'source_suffixes': ['.c'],
                      'source_names': [], 'binary_fixtures': [],
                      'build': {'required': ['src/main.c'], 'directories': ['src']},
                      'archive': {'required': ['src/main.c', 'README.md', '.gitignore',
                                               'scripts/project_files.json'], 'directories': ['src']}}
        self.save_rules()
        (self.root / 'src/main.c').write_text('int main(void) { return 0; }\n')
        (self.root / 'README.md').write_text('# Example\n')
        (self.root / '.gitignore').write_text('*.swp\n')

    def save_rules(self):
        (self.root / 'scripts/project_files.json').write_text(json.dumps(self.rules))

    def git(self, *arguments):
        return subprocess.check_output(['git', '-C', str(self.root), *arguments], stderr=subprocess.STDOUT)

    def commit_fixture(self):
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'test fixture')

    def test_only_build_inputs_change_identity(self):
        baseline = file_hashes(self.root)
        (self.root / 'README.md').write_text('# Updated docs\n')
        (self.root / 'src/.main.c.swp').write_bytes(b'editor data')
        (self.root / '.env').write_text('LOCAL_SETTING=value\n')
        self.assertEqual(baseline, file_hashes(self.root))
        (self.root / 'src/main.c').write_text('int main(void) { return 1; }\n')
        self.assertNotEqual(baseline, file_hashes(self.root))

    def test_missing_required_and_external_paths_rejected(self):
        (self.root / 'src/main.c').unlink()
        with self.assertRaises(ValueError):
            file_hashes(self.root)
        self.rules['build']['required'] = ['../outside.c']
        self.save_rules()
        with self.assertRaises(ValueError):
            file_hashes(self.root)

    def test_symlink_cannot_escape_policy(self):
        outside = self.root.parent / 'outside.c'
        outside.write_text('private data')
        (self.root / 'src/link.c').symlink_to(outside)
        with self.assertRaises(ValueError):
            file_hashes(self.root)

    def test_development_archive_omits_editor_and_unrelated_files(self):
        (self.root / 'src/.main.c.swp').write_text('editor')
        (self.root / 'notes.private').write_text('unrelated')
        archive = self.root.parent / 'source.tar'
        report = snapshot(self.root, archive)
        self.assertEqual(report['kind'], 'development')
        self.assertTrue(report['dirty'])
        with tarfile.open(archive) as source:
            self.assertEqual(set(source.getnames()), set(select_files(self.root, 'archive')))

    def test_formal_archive_requires_commit_and_rejects_changed_sources(self):
        archive = self.root.parent / 'source.tar'
        with self.assertRaises(ValueError):
            snapshot(self.root, archive, formal=True)
        self.commit_fixture()
        report = snapshot(self.root, archive, formal=True)
        self.assertFalse(report['dirty'])
        self.assertEqual(report['revision'], self.git('rev-parse', 'HEAD').decode().strip())
        (self.root / 'src/main.c').write_text('modified')
        with self.assertRaises(ValueError):
            snapshot(self.root, archive, formal=True)

    def test_tracked_unapproved_file_rejected_by_formal_archive(self):
        (self.root / 'notes.private').write_text('not in package')
        self.commit_fixture()
        with self.assertRaisesRegex(ValueError, 'declared package'):
            snapshot(self.root, self.root.parent / 'source.tar', formal=True)

    def test_document_links_are_repository_local(self):
        paths = {'README.md': self.root / 'README.md'}
        paths['README.md'].write_text('[file](src/main.c)\n')
        self.assertEqual(check_links(self.root, paths), [])
        paths['README.md'].write_text('[outside](../outside.md)\n')
        self.assertTrue(check_links(self.root, paths))


if __name__ == '__main__':
    unittest.main()
