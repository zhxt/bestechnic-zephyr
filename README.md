# bestechnic-zephyr

[简体中文](README.zh-CN.md)

This project integrates dual-core Zephyr on BES2700YP. BTH (STAR-MC1) and M55 (Cortex-M55) each run an independent Zephyr kernel and communicate through shared memory and mailbox notifications. Board support, bootstrap, and a dual-core communication validation app are included. One sysbuild invocation produces the complete flash image, `zephyr.bin`.

## System overview

The `bes2700yp_devkit` board has two Zephyr build targets:

| Core | Hardware processor | Zephyr board target |
|---|---|---|
| BTH | STAR-MC1 | `bes2700yp_devkit/bes2700yp/bth` |
| M55 | Cortex-M55 | `bes2700yp_devkit/bes2700yp/cm55` |

The BTH port currently builds with a Cortex-M33 target configuration; its hardware processor is STAR-MC1. Start sysbuild with the BTH target; M55 is built as a child image. The build combines both applications, bootstrap, and BES HAL libraries into `zephyr.bin`.

Bootstrap initializes hardware on BTH through BES HAL and starts BTH Zephyr. The BTH application then loads and starts M55 Zephyr. See the [hardware guide](docs/hardware/bes2700yp.md) for chip and board information and the [architecture guide](docs/architecture.md) for boot, packaging, and IPC details.

## Current support

The integration implements dual-core startup, basic kernel operation, and inter-core messaging. The chip capabilities below come from the BES [product page](https://www.bestechnic.com/en/article/78/64.html) and [brief data sheet](https://www.bestechnic.com/Uploads/keditor/file/20241010/20241010185852_50097.pdf); they are not a complete list of official SDK features.

| Area | Public chip capability | Integration status |
|---|---|---|
| Processors | Cortex-M55 and BTH STAR-MC1 | Two independent Zephyr kernels, startup, shared-memory messages, and mailbox notifications |
| UART | UART peripherals | BTH polling and interrupt driver implemented; Zephyr Serial/Console disabled by default; bootstrap UART carries logs |
| Memory and flash | SRAM, in-package flash, boot ROM | Runtime layout and HAL startup support; no Zephyr flash driver |
| Bluetooth | Dual-mode Bluetooth 5.3 and LE Audio | Not integrated |
| Audio | ADC/DAC, audio interfaces, ANC/EQ | Not integrated |
| Sensor Hub / NPU | STAR-MC1, sensor engine, BECO NPU | Not integrated |
| General peripherals | GPIO, I²C, SPI, PWM, GPADC, DMA, watchdog | No corresponding BES2700YP Zephyr drivers yet |
| Clock and power | Clock and power-management resources | HAL startup configuration at 24 MHz on both cores; Zephyr system power management not integrated |

See [supported features and limits](docs/hardware/bes2700yp.md#supported-features) for default settings and driver interfaces. [Testing](docs/testing.md#hardware-validation) describes hardware validation; implementation status alone is not a hardware-test result.

## Getting started

The build uses prebuilt libraries from `hal_bestechnic`. `west init` retrieves this integration, `west update` checks out pinned modules, and `west blobs fetch hal_bestechnic` downloads the libraries. A complete BES SDK is not needed for a normal build. See the [HAL guide](docs/hal.md) for version matching.

Follow [setup and build](docs/getting-started.md) to install host dependencies, create a Python virtual environment, and initialize a workspace from `main`. The required toolchain is GNU Arm Embedded **10.3-2021.10** ([Linux x86_64 download](https://developer.arm.com/-/media/Files/downloads/gnu-rm/10.3-2021.10/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2)); the guide includes copyable installation commands.

After setup, run a clean build from the workspace root containing `.venv/`, `zephyr/`, and `bestechnic-zephyr/`:

```sh
export BES_TOOLCHAIN_ROOT="$HOME/toolchains/gcc-arm-none-eabi-10.3-2021.10"
export CROSS_COMPILE="$BES_TOOLCHAIN_ROOT/bin/arm-none-eabi-"
unset TOOLCHAIN_ROOT
export ZEPHYR_BASE="$PWD/zephyr"
.venv/bin/python -m west build --sysbuild -p always \
  -b bes2700yp_devkit/bes2700yp/bth \
  bestechnic-zephyr/apps/bes2700yp/bth -d build/bes2700yp/main -- \
  -DZEPHYR_TOOLCHAIN_VARIANT=cross-compile \
  -DCROSS_COMPILE="$CROSS_COMPILE"
```

The full image is `build/bes2700yp/main/zephyr.bin`; accompanying files are in `release/` in that build directory. See [build outputs and verification](docs/getting-started.md#build-outputs-and-verification). Use the official BES **DldProductLine** tool to flash the complete image, following the target board's connection and tool instructions. Then [capture logs and validate](docs/testing.md#hardware-validation).

## Documentation

- [Setup and build](docs/getting-started.md)
- [BES2700YP hardware and supported features](docs/hardware/bes2700yp.md)
- [Testing and release validation](docs/testing.md)
- [Architecture and code ownership](docs/architecture.md)
- [Bestechnic HAL module](docs/hal.md)
- [Contributing](CONTRIBUTING.md)
- [Origin and licensing](THIRD_PARTY_NOTICES.md)

## License

Files marked `SPDX-License-Identifier: Apache-2.0` use this repository's [LICENSE](LICENSE). Vendor artifacts in the independent HAL module have separate terms; see [origin and licensing](THIRD_PARTY_NOTICES.md).
