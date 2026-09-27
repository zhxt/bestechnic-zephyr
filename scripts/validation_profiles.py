# SPDX-License-Identifier: Apache-2.0
"""Fixed validation scenarios, shared by configuration and release analyzers."""
from dataclasses import dataclass
from types import MappingProxyType

IDENTITY_SCHEMA = 3
VALIDATION_SCHEMA = 1


@dataclass(frozen=True)
class ValidationProfile:
    mode: int
    seconds: int
    heartbeat: int
    m55_restart: bool = False
    fault_case: int = 0
    recovery: bool = False


PROFILES = MappingProxyType({
    'ipc-sequential': ValidationProfile(1, 600, 600),
    'ipc-backpressure': ValidationProfile(2, 600, 610),
    'ipc-fault-injection': ValidationProfile(3, 600, 600),
    'ipc-backpressure-1h': ValidationProfile(2, 3600, 3610),
    'm55-restart': ValidationProfile(1, 600, 600, True),
    'm55-ready-timeout': ValidationProfile(1, 600, 600, True, 1),
    'm55-heartbeat-stop': ValidationProfile(1, 600, 600, True, 2),
    'm55-ready-recovery': ValidationProfile(1, 600, 600, True, 1, True),
    'm55-heartbeat-recovery': ValidationProfile(1, 600, 600, True, 2, True),
})


def get_profile(name):
    if not isinstance(name, str) or name not in PROFILES:
        raise ValueError('Unknown validation profile; choose: ' + ', '.join(PROFILES))
    return PROFILES[name]


def _check_fields(data, expected):
    if any(type(data.get(key)) is not type(value) or data[key] != value
           for key, value in expected.items()):
        raise ValueError('Validation profile metadata does not match its fixed parameters')
    if 'package' in data or 'message_package' in data:
        raise ValueError('Legacy validation metadata; use the analyzer from that release')


def validate_identity(identity):
    scenario = get_profile(identity.get('validation_profile'))
    _check_fields(identity, dict(schema=IDENTITY_SCHEMA,
                                validation_schema=VALIDATION_SCHEMA,
                                mode=scenario.mode, duration=scenario.seconds,
                                heartbeat=scenario.heartbeat))
    return scenario


def validate_manifest(manifest, *, restart=False, isolation=False, recovery=False):
    scenario = get_profile(manifest.get('validation_profile'))
    _check_fields(manifest, dict(validation_schema=VALIDATION_SCHEMA,
                                message_mode=scenario.mode,
                                message_seconds=scenario.seconds,
                                duration_seconds=scenario.heartbeat))
    if (scenario.m55_restart != restart or bool(scenario.fault_case) != isolation
            or scenario.recovery != recovery):
        raise ValueError('Validation profile requires a different analyzer')
    return scenario


def cmake_settings(name):
    scenario = get_profile(name)
    return ('# Generated validation settings; do not edit.\n'
            'set(BES_VALIDATION_PROFILES ' + ' '.join(PROFILES) + ')\n'
            'set(BES_VALIDATION_M55_RESTART '
            + ('ON' if scenario.m55_restart else 'OFF') + ')\n')
