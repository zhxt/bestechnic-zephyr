#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build-time identity, payload generation, packaging and offline release audit."""
import argparse
import ctypes
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

from audit_resources import audit as audit_resources
from audit_arbitration import audit as audit_arbitration
from audit_dual import (audit_doorbell, audit_m55, check_resource_contract,
                        audit_lifecycle, audit_service_entry, audit_reset_timer, audit_repark)
from check_bth_layout import audit, symbols
from pack_bth_payload import pack
from pack_m55_payload import parse_entry, parse_load_segments, run_readelf
from project_files import file_hashes
from module_lock import check_lock, check_modules
from package_source import hal_files, repository_state, require_clean, snapshot
from validation_profiles import (IDENTITY_SCHEMA, VALIDATION_SCHEMA, PROFILES, observation_contract,
                                 get_profile, validate_identity, cmake_settings)

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    data = value.encode() if isinstance(value, str) else value
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def save(path, obj):
    write(path, json.dumps(obj, indent=2, sort_keys=True) + '\n')


def check_pair(config, pair):
    match = re.search(r'^CONFIG_DUAL_CC_PAIR=(0x[0-9a-fA-F]+)$', config, re.M)
    if not match or int(match[1], 16) != pair:
        raise ValueError('pair identity mismatch')


def configure(a):
    # Development HAL variants remain protected by the artifact and manifest locks.
    modules = check_modules(ROOT, allow_dirty=() if a.formal else ('hal_bestechnic',))
    hal_manifest = json.loads((a.hal / 'manifest.json').read_text())
    compiler = subprocess.check_output([a.cross + 'gcc', '--version'], text=True).splitlines()[0]
    if compiler != hal_manifest['compiler']:
        raise ValueError('compiler differs from the audited HAL producer toolchain')
    scenario = get_profile(a.profile)
    duration, mode = scenario.seconds, scenario.mode
    resources = check_resource_contract(ROOT)
    hal_inputs = {name: sha(path) for name, path in hal_files(a.hal).items()}
    if sha(a.hal / 'manifest.json') != (ROOT / 'hal-release.sha256').read_text().strip():
        raise ValueError('HAL manifest.json SHA256 differs from hal-release.sha256')
    sources = file_hashes(ROOT)
    identity = dict(schema=IDENTITY_SCHEMA, chip='bes2700yp',
                    validation_schema=VALIDATION_SCHEMA, validation_profile=a.profile, mode=mode,
                    duration=duration, heartbeat=scenario.heartbeat,
                    observation=observation_contract(a.profile),
                    sources=sources, hal_release=sha(a.hal / 'manifest.json'),
                    modules=modules, compiler=compiler)
    if scenario.m55_restart:
        identity['lifecycle'] = resources['lifecycle']
        identity['reset_diagnostic'] = resources['reset_diagnostic']
        identity['repark_diagnostic'] = resources['repark_diagnostic']
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    identity['source_sha256'] = digest
    for name in ('m55_build', 'pair', 'profile'):
        identity[name] = int(hashlib.sha256((digest + ':' + name).encode()).hexdigest()[:8], 16)
    save(a.generated / 'identity.json', identity)
    write(a.generated / 'validation.cmake', cmake_settings(a.profile))
    states = {name: require_clean(path) if a.formal else repository_state(path)
              for name, path in [('integration', ROOT), ('hal', a.hal)]}
    save(a.generated / 'package-state.json', {'formal': a.formal, **states,
                                             'hal_inputs': hal_inputs})
    common = (f'CONFIG_DUAL_CC_PAIR=0x{identity["pair"]:08x}\n'
              f'CONFIG_DUAL_M55_BUILD=0x{identity["m55_build"]:08x}\n'
              f'CONFIG_DUAL_MSG_MODE={mode}\nCONFIG_DUAL_IPC_SECONDS={duration}\n')
    common += 'CONFIG_BES2700_M55_RESTART=' + ('y' if scenario.m55_restart else 'n') + '\n'
    common += f'CONFIG_BES2700_M55_FAULT_CASE={scenario.fault_case}\n'
    common += 'CONFIG_BES2700_M55_RECOVERY=' + ('y' if scenario.recovery else 'n') + '\n'
    common += f'CONFIG_BES2700_M55_RECOVERY_FAIL_STEP={scenario.recovery_fail_step}\n'
    write(a.generated / 'm55.conf', common)
    write(a.generated / 'bth.conf', common + f'CONFIG_DUAL_DURATION_SECONDS={identity["heartbeat"]}\n'
          + f'CONFIG_BES2700YP_GPIO_VALIDATION={scenario.gpio_mode}\n'
          + ('CONFIG_GPIO=y\nCONFIG_GPIO_BES2700YP=y\n' if scenario.gpio_api else ''))
    write(a.generated / 'boot_profile_id.h',
          f'#define BOOT_PROFILE_ID 0x{identity["profile"]:08x}U\n#define BOOT_PROFILE_VARIANT 2U\n')
    # Keep ROM/programmer metadata and reserved-sector reporting compatible.
    text = ('\nCHIP=best1600\nCHIP_SUBSYS=bth\nKERNEL=\nFLASH_BASE=0x34000000'
            '\nFLASH_NC_BASE=0x30000000\nFLASH_SIZE=0x800000\nNV_REC_DEV_VER=2'
            '\n__userdata_start=<##BASE##>\nUSER_SEC_SIZE=0x1000'
            '\n__aud_start=<##BASE##>\nAUD_SEC_SIZE=0'
            '\n__factory_start=<##BASE##>\nFACT_SEC_SIZE=0x1000'
            '\nBUILD_DATE=reproducible\nREV_INFO=bestechnic-zephyr:' + digest + '\n')
    write(a.generated / 'build_info.c', '/* SPDX-License-Identifier: Apache-2.0 */\n'
          'const char sys_build_info[] __attribute__((section(".build_info"))) = '
          + json.dumps(text) + ';\n')


def runtime_check(payload, generated):
    source = generated / 'image_validator.c'
    write(source, '#include "bes2700_dual_image.h"\n'
          'int check(const unsigned char *p, unsigned n, unsigned crc) '
          '{ return dual_image_check(p, n, crc); }\n')
    library = generated / 'image_validator.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                    '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                    str(source), '-o', str(library)], check=True)
    check = ctypes.CDLL(str(library)).check
    check.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint]
    check.restype = ctypes.c_int
    if check(payload, len(payload), zlib.crc32(payload)) != 0:
        raise ValueError('M55 payload rejected by the actual firmware validator')


def m55(a):
    identity = json.loads((a.generated / 'identity.json').read_text())
    validate_identity(identity)
    audit_m55(a.elf, a.cross)
    subprocess.run([sys.executable, str(ROOT / 'scripts/pack_m55_payload.py'), str(a.elf),
                    '--output', str(a.generated / 'm55-layout.json'), '--bes-segment-bin',
                    str(a.generated / 'm55.segment.bin'), '--boot-trace', '--cross-compile', a.cross], check=True)
    payload = (a.generated / 'm55.segment.bin').read_bytes()
    runtime_check(payload, a.generated)
    write(a.generated / 'm55_payload.h', '/* Generated from audited M55 ELF. */\n'
          f'#define M55_BUILD_ID 0x{identity["m55_build"]:08x}U\n'
          f'#define M55_PAYLOAD_CRC 0x{zlib.crc32(payload):08x}U\n'
          'static const unsigned char m55_payload[] __attribute__((aligned(4))) = {\n'
          + '\n'.join(','.join(f'0x{x:02x}' for x in payload[i:i+16]) + ','
                      for i in range(0, len(payload), 16)) + '\n};\n')


def bth(a):
    validate_identity(json.loads((a.generated / 'identity.json').read_text()))
    info = run_readelf(a.elf)
    payload, layout = pack(a.elf.read_bytes(), parse_load_segments(info), parse_entry(info),
                           (a.generated / 'identity.json').read_bytes())
    write(a.generated / 'bth.payload.bin', payload)
    layout.update(payload_sha256=hashlib.sha256(payload).hexdigest(), elf_sha256=sha(a.elf))
    save(a.generated / 'bth-layout.json', layout)


def fill_build_info(data, syms):
    if not 20 <= len(data) <= 0x800000:
        raise ValueError('invalid image length')
    magic, flags, reserved, info = struct.unpack_from('<4I', data)
    base = struct.unpack_from('<I', data, len(data) - 4)[0]
    if (magic, flags, reserved, base) != (0xffffffff, 0x00040000, 0, 0x34000000):
        raise ValueError('invalid pre-download header or load-address trailer')
    if syms.get('sys_build_info') != info or not 16 < info - base < len(data) - 4:
        raise ValueError('build_info pointer outside image or differs from ELF')
    start = info - base
    end = data.find(b'\0', start, len(data) - 4)
    if end < 0:
        raise ValueError('unterminated build_info')
    text = data[start:end]
    expected = {'__userdata_start', '__aud_start', '__factory_start'}
    found = set(x.decode() for x in re.findall(rb'(\w+)=<##BASE##>', text))
    if found != expected:
        raise ValueError('unexpected address placeholders')
    for name in sorted(expected):
        value = syms.get(name)
        if value is None or not 0x30000000 <= value < 0x30800000:
            raise ValueError('missing/out-of-range sector symbol: ' + name)
        old = name.encode() + b'=<##BASE##>'
        if text.count(old) != 1:
            raise ValueError('duplicate placeholder: ' + name)
        text = text.replace(old, f'{name}=0x{value:08X}'.encode())
    if len(text) != end - start or b'<##BASE##>' in text:
        raise ValueError('invalid build_info replacement')
    return data[:start] + text + data[end:]


def function_bytes(elf, name, cross):
    rows = subprocess.check_output([cross + 'nm', '-S', str(elf)], text=True).splitlines()
    row = next(x.split() for x in rows if x.split()[-1] == name)
    address, size = int(row[0], 16), int(row[1], 16)
    for segment in parse_load_segments(run_readelf(elf)):
        delta = address - segment['vaddr']
        if 0 <= delta and delta + size <= segment['filesz']:
            offset = segment['offset'] + delta
            return elf.read_bytes()[offset:offset + size]
    raise ValueError('function is not file backed: ' + name)


def check_inputs(identity, hal, package_state):
    validate_identity(identity)
    check_modules(ROOT, identity['modules'],
                  allow_dirty=() if package_state['formal'] else ('hal_bestechnic',))
    if file_hashes(ROOT) != identity['sources'] or check_lock(ROOT) != identity['modules']:
        raise ValueError('Build inputs changed after configuration; reconfigure before packaging')
    if sha(hal / 'manifest.json') != identity['hal_release']:
        raise ValueError('HAL manifest changed after configuration')
    if {name: sha(path) for name, path in hal_files(hal).items()} != package_state.get('hal_inputs'):
        raise ValueError('HAL inputs changed after configuration; reconfigure before packaging')
    if package_state['formal']:
        for name, path in [('integration', ROOT), ('hal', hal)]:
            require_clean(path, package_state[name])


def final(a):
    generated = a.generated
    build = generated.parent
    identity = json.loads((generated / 'identity.json').read_text())
    package_state = json.loads((generated / 'package-state.json').read_text())
    check_inputs(identity, a.hal, package_state)
    layout = json.loads((generated / 'bth-layout.json').read_text())
    belf, melf = build / 'bth/zephyr/zephyr.elf', build / 'm55/zephyr/zephyr.elf'
    syms = symbols(a.elf, a.cross)
    raw = generated / 'adapter.raw.bin'
    subprocess.run([a.cross + 'objcopy', '-R', '.trc_str', '-O', 'binary', str(a.elf), str(raw)], check=True)
    image = fill_build_info(raw.read_bytes(), syms)
    candidate = generated / 'zephyr.candidate.bin'
    write(candidate, image)
    report = audit(a.elf, belf, candidate, generated / 'bth.payload.bin', layout, a.cross)
    report['m55_memory'] = audit_m55(melf, a.cross)
    report['doorbell_endpoints'] = {core: audit_doorbell(elf, a.cross, core == 'bth',
                                  identity['duration'], identity['mode'],
                                  get_profile(identity['validation_profile']).m55_restart)
                                   for core, elf in [('bth', belf), ('m55', melf)]}
    mpayload = (generated / 'm55.segment.bin').read_bytes()
    if mpayload not in (generated / 'bth.payload.bin').read_bytes():
        raise ValueError('BTH does not embed this build of M55')
    report['actual_payload_runtime_validation'] = 'pass'
    report['startup_ram'] = {}
    fixture = json.loads((ROOT / 'platforms/bes2700yp/boot/t2-machine-code.json').read_text())
    for name in ('bth_crc32', 'bth_copy_bytes', 'bootprof_mark', 'bootprof_fast'):
        blob = function_bytes(a.elf, name, a.cross)
        if not syms['__boot_text_sram_start__'] <= syms[name] < syms[name] + len(blob) <= syms['__boot_text_sram_end__'] <= 0x510000:
            raise ValueError('startup RAM allocation: ' + name)
        if name in fixture['functions'] and hashlib.sha256(blob).hexdigest() != fixture['functions'][name]:
            raise ValueError('T2 machine code changed: ' + name)
        report['startup_ram'][name] = {'address': syms[name], 'bytes': len(blob)}
    disasm = subprocess.check_output([a.cross + 'objdump', '-d', '--disassemble=bth_boot_adapter_main', str(a.elf)], text=True)
    for name, count in [('bth_crc32', 3), ('bth_copy_bytes', 1)]:
        if len(re.findall(r'\bbl(?:\.w)?\s+[0-9a-f]+ <[^>]*' + name + '[^>]*>', disasm)) != count:
            raise ValueError('adapter call count: ' + name)
    for elf in (melf, belf, a.elf):
        if subprocess.check_output([a.cross + 'nm', '-u', str(elf)]).strip():
            raise ValueError('unresolved symbols: ' + str(elf))
        for segment in parse_load_segments(run_readelf(elf)):
            low, size = segment['vaddr'], segment['memsz']
            if size and any(low < end and start < low + size for start, end in
                            [(0x2015c000, 0x2015e000), (0x2055c200, 0x2055c800)]):
                raise ValueError('IPC/profile reservation overlap')
    for elf in (melf, belf):
        check_pair((elf.parent / '.config').read_text(), identity['pair'])
        dts = re.sub(r'/\*.*?\*/', '', (elf.parent / 'zephyr.dts').read_text(), flags=re.S)
        node = re.search(r'msg_shared: memory@2015c000\s*{([^}]+)}', dts)
        if not node or [int(x, 0) for x in re.findall(r'0x[0-9a-f]+', node[1])] != [0x2015c000, 0x2000]:
            raise ValueError('message DTS reservation')
    if any(re.match(r'hal_sys2bth_.*(?:open|start_recv|irq_init)', name) for name in syms):
        raise ValueError('vendor IPC owner linked')
    resources = check_resource_contract(ROOT)
    report['resource_contract'] = resources
    report['lifecycle_memory'] = audit_lifecycle((belf, melf, a.elf), a.cross, resources)
    report['service_entry'] = audit_service_entry(a.elf, belf, a.cross, ROOT, generated,
                                                  get_profile(identity['validation_profile']).m55_restart)
    report['resource_service'] = audit_resources(a.elf, belf, a.cross, ROOT, generated)
    layout['resource_service'] = report['resource_service']
    report['uart_resource_service'] = audit_resources(a.elf, belf, a.cross, ROOT, generated, uart=True)
    layout['uart_resource_service'] = report['uart_resource_service']
    report['arbitration_service'] = audit_resources(a.elf, belf, a.cross, ROOT, generated, arbitration=True)
    report['arbitration_service']['probe'] = get_profile(identity['validation_profile']).arbitration_probe
    layout['arbitration_service'] = report['arbitration_service']
    gpio_mode = get_profile(identity['validation_profile']).gpio_mode
    if gpio_mode:
        report['gpio_service'] = audit_resources(a.elf, belf, a.cross, ROOT, generated, gpio=True,
            gpio_api=get_profile(identity['validation_profile']).gpio_api)
        report['gpio_service']['mode'] = gpio_mode
        expected_cap = 56 if gpio_mode == 2 else 40
        if report['gpio_service']['capabilities'] != expected_cap:
            raise ValueError('GPIO build capability differs from profile')
        layout['gpio_service'] = report['gpio_service']
    report['arbitration_guard'] = audit_arbitration(a.elf, a.cross, get_profile(identity['validation_profile']).arbitration_probe)
    layout.update(version='V08c_QMSG_T2', build_architecture='bestechnic-zephyr-v1', test=8,
        log_version=3, prefix_version=1, duration_seconds=identity['heartbeat'],
        log_clock_state=[0x2055c180,0x2055c1a0], m55_build=f'0x{identity["m55_build"]:08x}',
        dual_layout='0x00080002', m55_elf_sha256=sha(melf), m55_payload_sha256=sha(generated / 'm55.segment.bin'),
        heartbeat_schedule='absolute_ms', heartbeat_period_ms=100, heartbeat_max_late_ms=20,
        message_version=2, message_layout=0x00090001, message_mode=identity['mode'],
        validation_schema=VALIDATION_SCHEMA, validation_profile=identity['validation_profile'],
        observation=identity['observation'],
        message_seconds=identity['duration'], message_pair=identity['pair'],
        progress_period=10, message_region=[0x2015c000,0x2015e000], profile_version=1, profile_variant=2,
        profile_id=f'0x{identity["profile"]:08x}', profile_points=12, profile_sampler=syms['bootprof_mark'] | 1,
        profile_buffer=0x2055c200, profile_size=1136, profile_crc_address=syms['bth_crc32'],
        profile_copy_address=syms['bth_copy_bytes'])
    if get_profile(identity['validation_profile']).m55_restart:
        report['reset_timer'] = audit_reset_timer(a.elf, a.cross, resources)
        report['repark'] = audit_repark(a.elf, a.cross)
        layout.update(version='M55_RESTART_V4_T2', dual_layout='0x000a0004',
                      restart_version=4, restart_rounds=11, restart_target=1000,
                      lifecycle_log=dict(version=2, module='LIFECYCLE', namespace='zephyr_lifecycle'),
                      lifecycle=identity['lifecycle'], reset_diagnostic=identity['reset_diagnostic'],
                      reset_sampler=report['reset_timer']['sampler'],
                      repark_diagnostic=identity['repark_diagnostic'])
    scenario = get_profile(identity['validation_profile'])
    fault_case = scenario.fault_case
    for elf in (belf, melf):
        conf = (elf.parent / '.config').read_text()
        if f'CONFIG_BES2700_M55_FAULT_CASE={fault_case}\n' not in conf:
            raise ValueError('fault injection configuration mismatch')
        if f'CONFIG_BES2700_M55_RECOVERY_FAIL_STEP={scenario.recovery_fail_step}\n' not in conf:
            raise ValueError('recovery failure configuration mismatch')
        if ('CONFIG_BES2700_M55_RECOVERY=y\n' in conf) != scenario.recovery:
            raise ValueError('recovery configuration mismatch')
    if fault_case:
        health = (ROOT / 'include/bestechnic/bes2700yp/bes2700_peer_health.h').read_text()
        contract = {}
        for key, name in [('ready_timeout_ms', 'READY_MS'),
                          ('heartbeat_timeout_ms', 'HEARTBEAT_MS'), ('ipc_timeout_ms', 'IPC_MS'),
                          ('fault_poll_ms', 'POLL_MS'), ('injection_stage', 'INJECTION_STAGE'),
                          ('injection_beats', 'INJECTION_BEATS')]:
            match = re.search(r'^#define BES_PEER_' + name + r' (\d+)U$', health, re.M)
            if not match:
                raise ValueError('missing peer health contract: ' + name)
            contract[key] = int(match[1])
        layout.update(version='M55_ISOLATION_V1_T2', isolation_version=1,
                      fault_case=fault_case, restart_rounds=1, **contract)
    if scenario.recovery:
        layout.update(version='M55_RECOVERY_V1_T2', recovery_version=1,
                      recovery_limit=1, injection_session=1, restart_rounds=2,
                      recovery_fail_step=scenario.recovery_fail_step)
    save(build / 'layout.json', layout)
    save(build / 'offline-validation.json', report)
    manifest = dict(identity, version='bestechnic-zephyr-v1', offline='pass', hardware='not_tested',
                    build=layout['build'], m55_build=layout['m55_build'], profile_id=layout['profile_id'],
                    message_pair=identity['pair'], message_seconds=identity['duration'],
                    message_mode=identity['mode'], duration_seconds=identity['heartbeat'],
                    firmware_sha256=hashlib.sha256(image).hexdigest())
    with tempfile.TemporaryDirectory(prefix='.release-', dir=build) as temporary:
        staging = Path(temporary) / 'release'
        staging.mkdir()
        write(staging / 'zephyr.bin', image)
        for src, name in [(a.elf, 'adapter.elf'),
                      (a.elf.with_suffix('.map'), 'adapter.map'), (belf, 'bth.elf'), (melf, 'm55.elf'),
                      (build / 'layout.json', 'layout.json'), (build / 'offline-validation.json', 'offline-validation.json'),
                      (generated / 'm55.segment.bin', 'm55.segment.bin'),
                      (generated / 'bth.payload.bin', 'bth.payload.bin'),
                      (a.hal / 'manifest.json', 'hal-manifest.json')]:
            shutil.copyfile(src, staging / name)
        for core, elf in [('bth', belf), ('m55', melf)]:
            for source, ext in [('.config', 'config'), ('zephyr.dts', 'dts'), ('zephyr.map', 'map')]:
                shutil.copyfile(elf.parent / source, staging / f'{core}.{ext}')
        for path in (ROOT / 'scripts').glob('analyze_*.py'):
            shutil.copyfile(path, staging / path.name)
        shutil.copyfile(ROOT / 'scripts/validation_profiles.py', staging / 'validation_profiles.py')
        provenance = {}
        for name, path, kind, filename in [('integration', ROOT, 'integration', 'integration-source.tar'),
                                            ('hal', a.hal, 'hal', 'hal-consumer.tar')]:
            provenance[name] = snapshot(path, staging / filename, kind,
                                        package_state['formal'], package_state[name])
        check_inputs(identity, a.hal, package_state)
        manifest['package_kind'] = 'formal' if package_state['formal'] else 'development'
        manifest['source_repositories'] = {k: {f: v[f] for f in ('revision', 'dirty')}
                                           for k, v in provenance.items()}
        save(staging / 'source-provenance.json', provenance)
        save(staging / 'manifest.json', manifest)
        write(staging / 'SHA256SUMS', ''.join(f'{sha(p)}  {p.name}\n' for p in sorted(staging.iterdir())))
        release, backup = build / 'release', Path(temporary) / 'previous'
        if release.exists():
            release.rename(backup)
        try:
            staging.rename(release)
        except OSError:
            if backup.exists():
                backup.rename(release)
            raise
    # Publish only after audit, dependency checks and source packaging all succeed.
    write(build / 'zephyr.bin', image)
    print(f'Offline audit PASS: {len(image)} bytes, sha256={sha(build / "zephyr.bin")}; hardware not tested')


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('step', choices=['configure', 'm55', 'bth', 'final'])
    parser.add_argument('--generated', type=Path, required=True)
    parser.add_argument('--elf', type=Path)
    parser.add_argument('--hal', type=Path)
    parser.add_argument('--cross', required=True)
    parser.add_argument('--profile', choices=tuple(PROFILES))
    parser.add_argument('--formal', action='store_true', help='Require clean committed sources for packaging')
    args = parser.parse_args()
    if args.step == 'configure' and args.profile is None:
        parser.error('configure requires --profile from the validation application')
    globals()[args.step](args)


if __name__ == '__main__':
    main()
