# Origin and License Scope

[简体中文](THIRD_PARTY_NOTICES.zh-CN.md)

This document identifies the principal origins, license boundaries, and reference locations for this repository and its firmware dependencies. Check the notices shipped with the versions you use, accompanying licenses, and applicable agreements for actual use and distribution terms.

## Files in this repository

This repository contains BES2700YP Zephyr integration code, example applications, and build tools. Files marked `SPDX-License-Identifier: Apache-2.0` use this repository's [LICENSE](LICENSE); preserve existing copyright and origin notices. This license does not change the terms of external dependencies or vendor artifacts.

Some documentation and configuration files do not yet carry SPDX identifiers. Determine their status from each file's notices and origin; do not treat every file as Apache-2.0 solely because the root contains `LICENSE`.

## Zephyr and CMSIS dependencies

West retrieves Zephyr, CMSIS, and CMSIS_6 at the revisions in [west.yml](west.yml); [module-lock.json](module-lock.json) records the same revisions for consistency checks. The locations below are relative to the workspace root:

| Dependency | Repository | Where to inspect terms |
|---|---|---|
| Zephyr | [zephyrproject-rtos/zephyr](https://github.com/zephyrproject-rtos/zephyr) | `zephyr/LICENSE`, `zephyr/README.license`, and file notices |
| CMSIS | [zephyrproject-rtos/cmsis](https://github.com/zephyrproject-rtos/cmsis) | `modules/hal/cmsis/LICENSE.txt` and file notices |
| CMSIS_6 | [zephyrproject-rtos/CMSIS_6](https://github.com/zephyrproject-rtos/CMSIS_6) | `modules/hal/cmsis_6/LICENSE` and file notices |

These repositories can contain components under different licenses. Inspect the notices included with the pinned revisions and the components actually used.

## BES HAL module

The project obtains `hal_bestechnic` at the commit pinned in [west.yml](west.yml). The module supplies prebuilt libraries and a vendor-derived linker script. This repository's [LICENSE](LICENSE) grants no additional rights to that vendor-origin content.

See `modules/hal/bestechnic/THIRD_PARTY_NOTICES.md` in the workspace for HAL origins, third-party notices, and license scope, and its `distribution.json` for public-distribution status. Check the module notices and applicable agreements before use or delivery.
