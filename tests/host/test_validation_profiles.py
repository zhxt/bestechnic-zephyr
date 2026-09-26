# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analyze_dual_message import analyze
from project_files import select_files
from test_message_parser import fixture, manifest
from validation_profiles import cmake_settings, get_profile, validate_identity, validate_manifest

ROOT = Path(__file__).resolve().parents[2]


class ValidationProfiles(unittest.TestCase):
    def test_fixed_parameters_and_manifest_mismatch(self):
        expected = {'ipc-sequential': (1, 600, 600),
                    'ipc-backpressure': (2, 600, 610),
                    'ipc-fault-injection': (3, 600, 600),
                    'ipc-backpressure-1h': (2, 3600, 3610)}
        for name, values in expected.items():
            with self.subTest(profile=name):
                scenario = get_profile(name)
                self.assertEqual((scenario.mode, scenario.seconds, scenario.heartbeat), values)
                self.assertEqual(validate_manifest(manifest(name)), scenario)
                for field in ('message_mode', 'message_seconds', 'duration_seconds'):
                    broken = manifest(name)
                    broken[field] += 1
                    self.assertEqual(analyze('', broken)['status'], 'fail')
                with self.assertRaises(ValueError):
                    validate_manifest(manifest(name), restart=True)

    def test_missing_legacy_and_invalid_metadata_cannot_pass(self):
        source = manifest()
        text = fixture(source)
        for field in ('validation_profile', 'validation_schema', 'message_seconds'):
            broken = dict(source)
            del broken[field]
            self.assertEqual(analyze(text, broken)['status'], 'fail')
        for field, value in [('validation_profile', 'Q2'), ('validation_profile', []),
                             ('validation_schema', 2), ('validation_schema', True),
                             ('message_mode', '2'), ('message_package', 'Q2')]:
            self.assertEqual(analyze(text, dict(source, **{field: value}))['status'], 'fail')

    def test_old_or_inconsistent_build_identity_is_rejected(self):
        identity = dict(schema=3, validation_schema=1, validation_profile='ipc-backpressure',
                        mode=2, duration=600, heartbeat=610)
        validate_identity(identity)
        for field, value in [('schema', 2), ('validation_schema', 0), ('duration', 3600),
                             ('heartbeat', 600), ('package', 'Q2')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_identity(dict(identity, **{field: value}))

    def test_cli_rejects_old_and_unknown_selection_before_building(self):
        with tempfile.TemporaryDirectory() as directory:
            base = [sys.executable, '-B', str(ROOT / 'scripts/firmware.py'), 'configure',
                    '--generated', directory, '--cross', 'unused-']
            for args in ([], ['--package', 'Q2'], ['--profile', 'Q2'],
                         ['--profile', 'unknown'], ['--profile', '']):
                result = subprocess.run(base + args, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertFalse((Path(directory) / 'identity.json').exists())
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/ci.py'),
                                     '--output', directory, '--packages', 'Q2'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('unrecognized arguments', result.stderr)

    def test_cmake_default_explicit_and_legacy_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sysbuild').mkdir()
            output = root / 'selection.txt'
            (root / 'sysbuild/dual.cmake').write_text(
                'file(WRITE "' + output.as_posix() + '" "${BES_VALIDATION_PROFILE}")\n')
            entry = ROOT / 'apps/bes2700yp/bth/sysbuild.cmake'
            base = ['cmake', '-DAPP_DIR=' + str(root / 'apps/bes2700yp/bth')]
            for args in ([], ['-DBES_VALIDATION_PROFILE=ipc-backpressure']):
                subprocess.run(base + args + ['-P', str(entry)], check=True, capture_output=True)
                self.assertEqual(output.read_text(), 'ipc-backpressure')
            for args in (['-DBES_PACKAGE=Q2'], ['-DBES_PACKAGE=Q3',
                          '-DBES_VALIDATION_PROFILE=ipc-backpressure']):
                result = subprocess.run(base + args + ['-P', str(entry)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('BES_PACKAGE was replaced', result.stderr)

    def test_profile_module_is_a_build_and_source_input(self):
        for scope in ('build', 'archive'):
            self.assertIn('scripts/validation_profiles.py', select_files(ROOT, scope))

    def test_restart_parameters_and_analyzer_separation(self):
        from test_restart_parser import manifest as restart_manifest
        from analyze_dual_restart import analyze as analyze_restart
        restart = get_profile('m55-restart')
        self.assertEqual((restart.mode, restart.seconds, restart.heartbeat), (1, 600, 600))
        self.assertTrue(restart.m55_restart)
        self.assertEqual(validate_manifest(restart_manifest(), restart=True), restart)
        self.assertEqual(analyze('', restart_manifest())['status'], 'fail')
        self.assertEqual(analyze_restart('', manifest())['status'], 'fail')
        self.assertIn('set(BES_VALIDATION_M55_RESTART ON)', cmake_settings('m55-restart'))
        self.assertIn('set(BES_VALIDATION_M55_RESTART OFF)', cmake_settings('ipc-backpressure'))
