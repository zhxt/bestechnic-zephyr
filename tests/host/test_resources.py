# SPDX-License-Identifier: Apache-2.0
import copy
import ctypes
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import analyze_resources as parser


class Resources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.directory = Path(cls.tmp.name)
        cls.includes = ['-I', str(ROOT / 'include/bestechnic/bes2700yp')]
        path = cls.directory / 'contract.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        *cls.includes, str(ROOT / 'platforms/bes2700yp/resources/contract.c'),
                        '-o', str(path)], check=True)
        cls.lib = ctypes.CDLL(str(path))
        cls.lib.bes_resource_buffer_valid.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cls.lib.bes_resource_descriptor_address_valid.argtypes = [ctypes.c_uint32]
        cls.lib.bes_resource_descriptor_valid.argtypes = [ctypes.POINTER(ctypes.c_uint32)]

    def test_buffers(self):
        for address in (0x20540000, 0x2055bfa0):
            self.assertEqual(self.lib.bes_resource_buffer_valid(address, 96), 1)
        for address in (0, 0x2053fffc, 0x20540001, 0x2055bfa4, 0x2055c000, 0x2015c000, 0xfffffffc):
            self.assertEqual(self.lib.bes_resource_buffer_valid(address, 96), 0)
        for size in (0, 95, 97, 0xffffffff):
            self.assertEqual(self.lib.bes_resource_buffer_valid(0x20540000, size), 0)

    def test_descriptor_span(self):
        for address in (0x34000000, 0x347fffe0, 0x14000000, 0x147fffe0):
            self.assertEqual(self.lib.bes_resource_descriptor_address_valid(address), 1)
        for address in (0, 0x34000001, 0x347fffe4, 0x34800000, 0x147fffe4, 0x20540000, 0xfffffffc):
            self.assertEqual(self.lib.bes_resource_descriptor_address_valid(address), 0)

    def test_descriptor_fields(self):
        words = [0x31534552, 1, 32, 1, 0x14000001, 96, 64, 0]
        self.assertTrue(self.lib.bes_resource_descriptor_valid((ctypes.c_uint32 * 8)(*words)))
        for i in range(8):
            bad = words.copy(); bad[i] ^= 1
            self.assertFalse(self.lib.bes_resource_descriptor_valid((ctypes.c_uint32 * 8)(*bad)))
        for entry in (0, 0x34000001, 0x14800001, 0x00510001, 0x20540001):
            bad = words.copy(); bad[4] = entry
            self.assertFalse(self.lib.bes_resource_descriptor_valid((ctypes.c_uint32 * 8)(*bad)))

    def test_actual_backend(self):
        exe = self.directory / 'backend'
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', '-fno-sanitize-recover=all', *self.includes,
                        '-I', str(ROOT.parent / 'modules/hal/bestechnic/include'),
                        str(ROOT / 'tests/dual_message/resource_service.c'),
                        str(ROOT / 'platforms/bes2700yp/resources/contract.c'), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=10)

    def test_actual_client(self):
        exe = self.directory / 'client'
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', '-fno-sanitize-recover=all', *self.includes,
                        str(ROOT / 'tests/dual_message/resource_client.c'),
                        str(ROOT / 'platforms/bes2700yp/resources/client.c'),
                        str(ROOT / 'platforms/bes2700yp/resources/contract.c'),
                        str(ROOT / 'platforms/bes2700yp/boot/service_contract.c'),
                        '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=10)

    def fixture(self):
        manifest = dict(build='0x123', restart_version=4, resource_service=dict(abi=1, capabilities=1))
        lines = []
        for phase in (0, 3, 4):
            if phase:
                lines.append(f'1/I/BTH/LIFECYCLE/MAIN | zephyr_lifecycle reset op={phase} rc=0 !')
            fields = dict.fromkeys(parser.FIELDS, 0)
            fields.update(version=1, build=0x123, expected=phase, abi=1, bytes=64,
                          valid=7 if phase else 1, phase=phase, clocks_24m=int(bool(phase)),
                          core_vtor=0x200c0000 if phase else 0)
            lines.append('1/I/BTH/RESOURCE/MAIN | zephyr_resource snapshot ' +
                         ' '.join(f'{k}={v}' for k, v in fields.items()) + ' !')
        return '\n'.join(lines), manifest

    def analyze(self, text, manifest):
        base = dict(status='pass', session_count=1, sessions=[dict(status='pass', errors=[], missing=[],
                    scopes=dict(short=dict(status='pass')), overall_status='pass', complete=True)])
        return parser.run(text, manifest, lambda clean: copy.deepcopy(base))

    def test_log_success(self):
        text, manifest = self.fixture()
        self.assertEqual(self.analyze(text, manifest)['status'], 'pass')

    def test_log_rejects_corruption(self):
        text, manifest = self.fixture()
        for bad in (text.replace('version=1', 'version=2'), text.replace('rc=0', 'rc=1'),
                    text.replace('build=291', 'build=292'), text.replace('/RESOURCE/', '/LOADER/'),
                    text + '\n' + text.splitlines()[-1], text.replace('bytes=64', 'bytes=32'),
                    text.replace('valid=7', 'valid=1'), text.replace('snapshot ', 'snapshot rc=0 '),
                    text.replace('zephyr_lifecycle reset op=3', 'zephyr_lifecycle reset op=2')):
            self.assertEqual(self.analyze(bad, manifest)['status'], 'fail', bad)

    def test_log_missing_downgrades_scope(self):
        text, manifest = self.fixture()
        result = self.analyze('\n'.join(text.splitlines()[:-1]), manifest)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['sessions'][0]['scopes']['short']['status'], 'incomplete')

    def test_legacy_manifest(self):
        self.assertEqual(self.analyze('legacy', {})['status'], 'pass')

    def test_full_scenario_parsers_with_resource_records(self):
        from test_observation_parser import cases, fixture
        for analyzer, old_manifest, legacy in cases():
            manifest, full, short = fixture(old_manifest, legacy)
            manifest['resource_service'] = dict(abi=1, capabilities=1)
            lines, emitted = [], set()
            for line in short.splitlines():
                lines.append(line)
                phase = None
                if 'zephyr_bth stage=main !' in line:
                    phase = 0
                elif 'zephyr_dual stage id=6 ' in line or ('zephyr_lifecycle reset ' in line and ' op=3 ' in line):
                    phase = 3
                elif manifest.get('restart_version') and 'zephyr_observe functional ' in line:
                    phase = 4
                if phase is None or phase in emitted:
                    continue
                emitted.add(phase)
                d = dict.fromkeys(parser.FIELDS, 0)
                d.update(version=1, build=int(manifest['build'], 0), expected=phase, abi=1, bytes=64,
                         valid=7 if phase else 1, phase=phase, clocks_24m=int(bool(phase)),
                         core_vtor=0x200c0000 if phase else 0)
                if phase == 4:
                    lines.pop()
                lines.append(line.split('/')[0] + '/I/BTH/RESOURCE/MAIN | zephyr_resource snapshot ' +
                             ' '.join(f'{k}={v}' for k, v in d.items()) + ' !')
                if phase == 4:
                    lines.append(line)
            text = '\n'.join(lines)+'\n'
            result = analyzer.analyze(text, manifest, 'short')
            self.assertEqual(result['status'], 'pass', (manifest['validation_profile'], result))
            self.assertEqual(len(result['sessions'][0]['resource_snapshots']), len(emitted))
            bad = text.replace('clocks_24m=1', 'clocks_24m=0')
            self.assertEqual(analyzer.analyze(bad, manifest, 'short')['status'], 'fail')
            missing = '\n'.join(line for line in lines if 'zephyr_resource' not in line)+'\n'
            self.assertEqual(analyzer.analyze(missing, manifest, 'short')['status'], 'incomplete')

    def test_elf_file_backing_and_control_flow(self):
        from audit_resources import file_span, check_control_flow
        segment = dict(vaddr=0x14000000, offset=32, filesz=16, flags='R E')
        self.assertEqual(file_span([segment], 0x14000004, 12, True), 36)
        for address, size in ((0x14000004, 13), (0x13fffffc, 4), (0x14000010, 1), (0x14000000, 0)):
            with self.assertRaises(ValueError):
                file_span([segment], address, size, True)
        with self.assertRaises(ValueError):
            file_span([dict(segment, flags='RW')], 0x14000000, 4)
        with self.assertRaises(ValueError):
            file_span([dict(segment, flags='R')], 0x14000000, 4, True)
        # Shared return behind a forward branch is acyclic.
        check_control_flow([(0, 'cbz', 'r0, 6 <entry+0x6>'), (2, 'pop', '{r4, pc}'),
                            (6, 'b.n', '2 <entry+0x2>')], 'entry')
        check_control_flow([(0, 'ldmia.w', 'sp!, {r4, pc}'), (4, 'b.n', '0 <entry>')], 'entry')
        with self.assertRaises(ValueError):
            check_control_flow([(0, 'nop', ''), (2, 'bne.n', '0 <entry>'),
                                (4, 'bx', 'lr')], 'entry')
