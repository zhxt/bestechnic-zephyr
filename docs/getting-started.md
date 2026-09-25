# Setup and Build

[简体中文](getting-started.zh-CN.md)

## Host environment

Commands use Bash and Ubuntu 24.04 LTS x86_64. On another Linux x86_64 host, first provide Python 3.12 with venv, CMake 3.28.0 or later, Ninja, dtc 1.4.6 or later, Git, a host C compiler, and binutils.

```sh
sudo apt-get update
sudo apt-get install -y \
  git curl ca-certificates build-essential binutils \
  cmake ninja-build device-tree-compiler gperf bzip2 xz-utils \
  python3.12 python3.12-venv python3.12-dev

python3.12 --version
cmake --version
ninja --version
dtc --version
```

These versions match the Zephyr revision pinned in [west.yml](../west.yml). Python dependencies will be installed in a workspace virtual environment. The firmware uses GNU Arm Embedded **10.3-2021.10**. Isolated-build testing additionally needs bubblewrap; see [testing](testing.md#isolated-build).

## Install the toolchain

Download [GNU Arm Embedded 10.3-2021.10 for Linux x86_64](https://developer.arm.com/-/media/Files/downloads/gnu-rm/10.3-2021.10/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2) from Arm, extract it under `$HOME/toolchains/`, and set the compiler prefix. If already installed, skip download/extraction and point `BES_TOOLCHAIN_ROOT` to its actual root:

```sh
mkdir -p "$HOME/toolchains"
curl --fail --location --retry 3 \
  --output "$HOME/toolchains/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2" \
  https://developer.arm.com/-/media/Files/downloads/gnu-rm/10.3-2021.10/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2 && \
tar -xjf "$HOME/toolchains/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2" \
  -C "$HOME/toolchains"
export BES_TOOLCHAIN_ROOT="$HOME/toolchains/gcc-arm-none-eabi-10.3-2021.10"
export CROSS_COMPILE="$BES_TOOLCHAIN_ROOT/bin/arm-none-eabi-"
"${CROSS_COMPILE}gcc" --version
```

The toolchain root contains `bin/`. Do not use Zephyr's `TOOLCHAIN_ROOT` to represent the compiler installation: Zephyr uses that variable for its own CMake toolchain files. The expected first version line is:

```text
arm-none-eabi-gcc (GNU Arm Embedded Toolchain 10.3-2021.10) 10.3.1 20210824 (release)
```

The build compares this line with `compiler` in HAL `manifest.json` and stops on mismatch. `CROSS_COMPILE` is a prefix ending in `arm-none-eabi-`; the build appends tool names such as `gcc` and `objcopy`. Run subsequent commands in the same terminal, or [restore the environment](#ongoing-development) later.

## Workspace

The integration URL is [zhxt/bestechnic-zephyr](https://github.com/zhxt/bestechnic-zephyr); the HAL module URL is [zhxt/hal_bestechnic](https://github.com/zhxt/hal_bestechnic). Remote setup requires both repositories, the HAL commit in [west.yml](../west.yml), and its blob files to be published and accessible.

Create a dedicated directory outside any other west workspace:

```sh
mkdir -p "$HOME/bestechnic-workspace"
cd "$HOME/bestechnic-workspace"
```

The sequence is: create a workspace and venv; retrieve code and Python dependencies; fetch HAL libraries; check dependencies; build the `main` defaults; verify the image; flash with the board's official DldProductLine procedure; save logs and validate. `west update` selects the HAL revision and `west blobs fetch hal_bestechnic` downloads its libraries. See [HAL version matching](hal.md).

```text
$HOME/bestechnic-workspace/
├── bestechnic-zephyr/          integration and west manifest
├── zephyr/                    pinned revision
├── modules/hal/
│   ├── cmsis/
│   ├── cmsis_6/
│   └── bestechnic/             pinned HAL module
├── .west/                     west state
├── .venv/                     Python environment
└── build/                     outputs and logs
```

## Initialize and check dependencies

Run setup, checks, and builds from the workspace root created above.

### Create a Python virtual environment

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install west==1.4.0
```

Use `.venv/bin/python` directly; activation is unnecessary. Do not use `sudo pip` or install project dependencies into system Python. If an appropriate Python 3.12 venv already exists, reuse it.

### Retrieve code and modules

Clear `ZEPHYR_BASE` from other workspaces before initialization; set it again for the build:

```sh
unset ZEPHYR_BASE
.venv/bin/python -m west init \
  -m https://github.com/zhxt/bestechnic-zephyr.git --mr main .
.venv/bin/python -m west update
.venv/bin/python -m pip install -r bestechnic-zephyr/requirements.txt
.venv/bin/python -m west blobs fetch hal_bestechnic
```

`west init` creates `.west/` and checks out the integration at `bestechnic-zephyr/`. `west update` retrieves pinned Zephyr, CMSIS, CMSIS_6, and HAL. Install west first because the full requirements file references the pinned Zephyr requirements, which are available after `west update`. Blob fetch then downloads and checks the three libraries; builds do not download them automatically.

If the integration has already been cloned into `bestechnic-zephyr/`, select `main` and replace remote `west init` with local initialization; then run the remaining update, pip, and blob commands:

```sh
git -C bestechnic-zephyr switch main
.venv/bin/python -m west init -l bestechnic-zephyr
```

`west init -l` uses the currently checked-out integration branch. In an existing project workspace with the correct `bestechnic-zephyr/west.yml`, skip `west init`. An existing `.west/` alone does not prove that the manifest belongs to this project.

### Check dependencies

After module synchronization, Python installation, and blob fetch:

```sh
.venv/bin/python bestechnic-zephyr/scripts/check_repo.py
```

Expect `status: pass` and empty `issues`. The check covers file boundaries, document link targets, west/lock consistency, and HAL hashes. `publication_pending` reports distribution status and publication setup separately; local success is not proof of public-distribution authorization or hardware validation. Builds also check actual module revisions; Zephyr, CMSIS, and CMSIS_6 must be unmodified. See [candidate provenance](../CONTRIBUTING.md#candidate-package-provenance) for HAL local changes and formal checkouts.

## Build

Start sysbuild from the BTH board target. It builds M55, BTH, and bootstrap together. The following cleans and builds the default `main` configuration; `-p always` clears the chosen build directory and its old CMake cache:

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

The normal build compiles both cores and bootstrap, packages the image, and runs offline audit. To also run host regressions:

```sh
cmake --build build/bes2700yp/main --target release
```

The target name `release` does not claim hardware acceptance or public release. Source archives default to `development` mode; see [formal candidates](../CONTRIBUTING.md#candidate-package-provenance).

## Build outputs and verification

Paths below are relative to `build/bes2700yp/main/`:

| Output | Purpose |
|---|---|
| `zephyr.bin` | Complete flash image, duplicated in `release/zephyr.bin` |
| `release/layout.json` | Image layout and log-acceptance parameters |
| `release/offline-validation.json` | Offline audit results |
| `release/manifest.json` | Image identity, build configuration, and validation status |
| `release/source-provenance.json` | Integration and HAL provenance |
| `release/integration-source.tar`, `release/hal-consumer.tar` | Source and HAL archives |
| `release/SHA256SUMS` | Package checksum list |

`release/` also contains ELF, map, configuration, DTS, and log-analysis scripts. The per-core `bth/zephyr/zephyr.bin` and `m55/zephyr/zephyr.bin` are not substitutes for the complete flash image.

Verify the package from the workspace root:

```sh
(
  cd build/bes2700yp/main/release || exit 1
  sha256sum -c SHA256SUMS
)
```

Every entry should say `OK`, with exit code 0. This verifies package integrity, not [hardware behavior](testing.md#hardware-validation). `build/` can be removed and rebuilt; copy images, reports, manifests, and logs you need to retain outside it first.

## Flashing requirements

Use the official BES **DldProductLine** tool to flash the complete `build/bes2700yp/main/zephyr.bin`. The repository has no `west flash` runner. Follow the official procedure for the target board; tool configuration and connection details are not yet specified here. Runtime addresses are not flash addresses.

Before flashing, obtain the board's power, serial, and download connection details and the applicable DldProductLine version/configuration. See [board information](hardware/bes2700yp.md#boards-and-build-targets). A successful build does not establish physical-board compatibility. Save serial logs after flashing, then validate them with the image's `release/layout.json` and packaged analyzers; see [testing](testing.md#hardware-validation).

## Ongoing development

In a new terminal, restore the workspace and environment; reinstalling the toolchain or venv is unnecessary:

```sh
cd "$HOME/bestechnic-workspace"
export BES_TOOLCHAIN_ROOT="$HOME/toolchains/gcc-arm-none-eabi-10.3-2021.10"
export CROSS_COMPILE="$BES_TOOLCHAIN_ROOT/bin/arm-none-eabi-"
unset TOOLCHAIN_ROOT
export ZEPHYR_BASE="$PWD/zephyr"
```

`west update` updates dependencies in the manifest, not the integration repository itself. To get newer `main`, first save local integration/HAL work and ensure the integration checkout is clean:

```sh
git -C bestechnic-zephyr switch main
git -C bestechnic-zephyr pull --ff-only origin main
.venv/bin/python -m west update
.venv/bin/python -m pip install -r bestechnic-zephyr/requirements.txt
.venv/bin/python -m west blobs fetch hal_bestechnic
.venv/bin/python bestechnic-zephyr/scripts/check_repo.py
```

Then perform a [clean build](#build). The manifest selects the matching HAL revision; do not follow the HAL repository's `main` separately.
