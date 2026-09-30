# SPDX-License-Identifier: Apache-2.0
"""Fixed validation scenarios, shared by configuration and release analyzers."""
import json
from dataclasses import dataclass
from types import MappingProxyType

IDENTITY_SCHEMA = 4
VALIDATION_SCHEMA = 2


@dataclass(frozen=True)
class ValidationProfile:
    mode: int
    seconds: int
    heartbeat: int
    m55_restart: bool = False
    fault_case: int = 0
    recovery: bool = False
    recovery_fail_step: int = 0
    arbitration_probe: bool = False
    gpio_mode: int = 0
    gpio_api: bool = False
    gpio_irq: bool = False


PROFILES = MappingProxyType({
    'gpio-irq-input': ValidationProfile(1, 600, 600, gpio_mode=1, gpio_api=True, gpio_irq=True),
    'gpio-irq-restart': ValidationProfile(1, 600, 600, True, gpio_mode=1, gpio_api=True, gpio_irq=True),
    'gpio-irq-recovery': ValidationProfile(1, 600, 600, True, 3, True, gpio_mode=1, gpio_api=True, gpio_irq=True),
    'gpio-api-input': ValidationProfile(1, 600, 600, gpio_mode=1, gpio_api=True),
    'gpio-api-led-restart': ValidationProfile(1, 600, 600, True, gpio_mode=2, gpio_api=True),
    'gpio-input': ValidationProfile(1, 600, 600, gpio_mode=1),
    'gpio-led': ValidationProfile(1, 600, 600, gpio_mode=2),
    'ipc-sequential': ValidationProfile(1, 600, 600),
    'ipc-backpressure': ValidationProfile(2, 600, 610),
    'ipc-fault-injection': ValidationProfile(3, 600, 600),
    'ipc-backpressure-1h': ValidationProfile(2, 3600, 3610),
    'resource-arbitration': ValidationProfile(1, 600, 600, True, arbitration_probe=True),
    'm55-restart': ValidationProfile(1, 600, 600, True),
    'm55-ready-timeout': ValidationProfile(1, 600, 600, True, 1),
    'm55-heartbeat-stop': ValidationProfile(1, 600, 600, True, 2),
    'm55-ready-recovery': ValidationProfile(1, 600, 600, True, 1, True),
    'm55-heartbeat-recovery': ValidationProfile(1, 600, 600, True, 2, True),
    'm55-ipc-stall-recovery': ValidationProfile(1, 600, 600, True, 3, True, 0),
    'm55-quiesce-recovery': ValidationProfile(1, 600, 600, True, 4, True, 0),
    'm55-fatal-recovery': ValidationProfile(1, 600, 600, True, 5, True, 0),
    'm55-fatal-unreadable-recovery': ValidationProfile(1, 600, 600, True, 6, True, 0),
    'm55-repark-failure': ValidationProfile(1, 600, 600, True, 2, True, 1),
    'm55-load-failure': ValidationProfile(1, 600, 600, True, 2, True, 3),
    'm55-recovery-ready-failure': ValidationProfile(1, 600, 600, True, 2, True, 5),

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


def observation_contract(name):
    scenario = get_profile(name)
    if scenario.mode == 2:
        return dict(version=1, kind='sustained', scopes=['long'],
                    long_ms=scenario.heartbeat * 1000)
    return dict(version=1, kind='terminal', scopes=['functional', 'short', 'long'],
                short_ms=60000, long_ms=600000, limit_ms=660000,
                functional_limit_ms=600000 if scenario.m55_restart else 590000,
                sample_period_ms=1000)


def layered(manifest):
    return manifest.get('validation_schema') == 2 and manifest.get('message_mode') != 2


def _schema(data):
    schema = data.get('validation_schema')
    if type(schema) is not int or schema not in (1, 2):
        raise ValueError('Unsupported validation schema; use the release analyzer')
    if schema == 2 and json.dumps(data.get('observation'), sort_keys=True) != json.dumps(observation_contract(data['validation_profile']), sort_keys=True):
        raise ValueError('Observation contract mismatch')
    if schema == 1 and get_profile(data['validation_profile']).gpio_irq:
        raise ValueError('GPIO IRQ profiles require layered observation evidence')
    if schema == 1 and 'observation' in data:
        raise ValueError('Legacy validation cannot declare observation scopes')
    return schema


def validate_identity(identity):
    scenario = get_profile(identity.get('validation_profile'))
    schema = _schema(identity)
    _check_fields(identity, dict(schema=4 if schema == 2 else 3,
                                validation_schema=schema,
                                mode=scenario.mode, duration=scenario.seconds,
                                heartbeat=scenario.heartbeat))
    return scenario


def validate_manifest(manifest, *, restart=False, isolation=False, recovery=False):
    scenario = get_profile(manifest.get('validation_profile'))
    schema = _schema(manifest)
    _check_fields(manifest, dict(validation_schema=schema,
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
            + ('ON' if scenario.m55_restart else 'OFF') + ')\n'
            'set(BES_VALIDATION_ARBITRATION_PROBE '
            + ('ON' if scenario.arbitration_probe else 'OFF') + ')\n'
            + f'set(BES_VALIDATION_GPIO_MODE {scenario.gpio_mode})\n'
            + 'set(BES_VALIDATION_GPIO_IRQ ' + ('ON' if scenario.gpio_irq else 'OFF') + ')\n'
            + 'set(BES_VALIDATION_GPIO_API ' + ('ON' if scenario.gpio_api else 'OFF') + ')\n')
