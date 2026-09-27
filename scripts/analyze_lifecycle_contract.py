# SPDX-License-Identifier: Apache-2.0
"""Versioned text-log contract; independent of the shared-memory ABI."""
LOG_MODULE = 'LIFECYCLE'
LOG_NAMESPACE = 'zephyr_lifecycle'
LOG_CONTRACT = dict(version=2, module=LOG_MODULE, namespace=LOG_NAMESPACE)
FAULT_REASONS = {1: 1, 2: 2, 3: 4, 4: 5, 5: 6, 6: 2}
