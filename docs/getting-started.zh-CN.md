# 环境准备与构建

[English](getting-started.md)

## 主机环境

本文使用 Bash，主机安装示例面向 Ubuntu 24.04 LTS x86_64。其他 Linux x86_64 环境需先准备 Python 3.12（含 venv）、CMake 3.28.0 或更新版本、Ninja、dtc 1.4.6 或更新版本、Git、主机 C 编译器和 binutils，再继续后续步骤。

在 Ubuntu 24.04 上安装主机依赖：

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

这些版本要求对应 [west.yml](../west.yml) 指定的 Zephyr 提交。Python 项目依赖将在工作区的虚拟环境中安装；`python3.12-venv` 提供创建该环境所需的支持。固件使用 GNU Arm Embedded **10.3-2021.10**，安装步骤见下节。隔离构建验证另需 bubblewrap，详见[测试说明](testing.zh-CN.md#隔离构建)。

## 工具链安装

以下命令从 Arm 官方地址下载 [GNU Arm Embedded 10.3-2021.10（Linux x86_64）](https://developer.arm.com/-/media/Files/downloads/gnu-rm/10.3-2021.10/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2)，下载成功后解压到 `$HOME/toolchains/`，并设置编译器路径。已有该版本时跳过下载和解压，直接设置实际安装路径：

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

如使用其他安装位置，将 `BES_TOOLCHAIN_ROOT` 改为实际目录；它应指向包含 `bin/` 的工具链根目录。Zephyr 将 `TOOLCHAIN_ROOT` 用于查找自身的 CMake 工具链文件，不能用它表示编译器安装目录。预期版本输出的首行为：

```text
arm-none-eabi-gcc (GNU Arm Embedded Toolchain 10.3-2021.10) 10.3.1 20210824 (release)
```

构建会将此首行与 HAL 模块 `manifest.json` 中的 `compiler` 字段比较，不一致时停止。`CROSS_COMPILE` 是以 `arm-none-eabi-` 结尾的工具前缀，构建会在其后追加 `gcc`、`objcopy` 等工具名。后续命令在同一终端执行；新终端的恢复步骤见[后续开发](#后续开发)。

## 工作区

集成仓地址为 [zhxt/bestechnic-zephyr](https://github.com/zhxt/bestechnic-zephyr)，HAL 模块仓库地址为 [zhxt/hal_bestechnic](https://github.com/zhxt/hal_bestechnic)。以下远程初始化命令以两个仓库、[west.yml](../west.yml) 指定的 HAL 提交及对应 blob 下载文件已发布且可访问为前提。

创建独立工作区，不要将其放在另一个 west 工作区内部。本文统一使用 `$HOME/bestechnic-workspace/`：

```sh
mkdir -p "$HOME/bestechnic-workspace"
cd "$HOME/bestechnic-workspace"
```

首次使用依次完成：创建工作区和 venv → 获取代码并安装 Python 依赖 → 下载 HAL 静态库 → 检查依赖 → 构建 `main` 默认配置 → 核对完整镜像 → 按目标板官方流程用 DldProductLine 刷写 → 保存日志并验收。HAL 模块随 `west update` 按 [west.yml](../west.yml) 指定的提交同步，静态库通过 `west blobs fetch hal_bestechnic` 获取，匹配要求见 [HAL 说明](hal.zh-CN.md)。后续步骤使用同一终端中的环境变量。

初始化和构建后的目录布局如下：

```text
$HOME/bestechnic-workspace/
├── bestechnic-zephyr/          集成仓及 west manifest
├── zephyr/                    固定提交
├── modules/hal/
│   ├── cmsis/
│   ├── cmsis_6/
│   └── bestechnic/             HAL 模块仓库，固定提交
├── .west/                     west 本地状态
├── .venv/                     Python 环境
└── build/                     生成物和日志
```

## 初始化与依赖检查

以下初始化、检查和构建命令均从上节创建的工作区根目录执行。

### 创建 Python 虚拟环境

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install west==1.4.0
```

后续命令均通过 `.venv/bin/python` 使用该环境，无需激活虚拟环境。不要使用 `sudo pip` 或把依赖安装到系统 Python。已有本项目的 Python 3.12 虚拟环境时，可跳过创建命令，继续安装所需依赖。

### 获取代码与模块

首次初始化时，先清除其他工作区可能遗留的 `ZEPHYR_BASE`；构建步骤会重新设置它：

```sh
unset ZEPHYR_BASE
.venv/bin/python -m west init \
  -m https://github.com/zhxt/bestechnic-zephyr.git --mr main .
.venv/bin/python -m west update
.venv/bin/python -m pip install -r bestechnic-zephyr/requirements.txt
.venv/bin/python -m west blobs fetch hal_bestechnic
```

`west init` 将集成仓放到 `bestechnic-zephyr/` 并创建 `.west/`；`west update` 按 [west.yml](../west.yml) 同步 Zephyr、CMSIS、CMSIS_6 和 `hal_bestechnic`。先安装 west 是因为完整 Python 依赖文件引用该 Zephyr 提交自带的基础依赖清单，该文件在 `west update` 后才存在。随后 `west blobs fetch` 按 HAL 模块 `zephyr/module.yml` 下载三个静态库并核对 SHA256；构建期间不自动下载。

若已将集成仓克隆到工作区的 `bestechnic-zephyr/`，先切换到 `main`，再将上面的远程 `west init` 命令替换为本地初始化命令；之后照常执行 `west update`、依赖安装和 `west blobs fetch hal_bestechnic`：

```sh
git -C bestechnic-zephyr switch main
.venv/bin/python -m west init -l bestechnic-zephyr
```

`west init -l` 使用本地集成仓当前检出的分支，不会自动切换到 `main`。

如果工作区已经使用本项目的 `bestechnic-zephyr/west.yml`，跳过 `west init`。仅存在 `.west/` 不能说明 manifest 正确；其他项目的 west 工作区应另建目录。

### 检查依赖

模块同步、Python 依赖安装和 HAL 静态库下载完成后，运行仓库检查：

```sh
.venv/bin/python bestechnic-zephyr/scripts/check_repo.py
```

本地检查应返回 `status: pass` 且 `issues` 为空，检查内容包括文件边界、文档链接目标文件、`west.yml` 与 `module-lock.json` 的一致性，以及 HAL 文件哈希。`publication_pending` 单独报告分发状态和发布配置；本地检查通过不代表已获公开分发授权或完成实板验收。构建时还会核对四个模块实际 checkout 的提交；Zephyr、CMSIS 和 CMSIS_6 须无本地修改。HAL 本地修改及正式候选要求见[候选包来源](../CONTRIBUTING.zh-CN.md#候选包来源)。

## 构建

从 BTH 板级目标启动 sysbuild，构建过程同时生成 M55、BTH 和 bootstrap，无需分别执行两核构建。

以下命令使用项目默认配置，对 `main` 分支源码执行干净构建。`-p always` 会清理并重新生成指定构建目录，避免沿用旧的配置缓存。

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

普通构建完成两核及 bootstrap 编译、镜像打包和离线审计。需要同时运行主机回归时，执行：

```sh
cmake --build build/bes2700yp/main --target release
```

`release` 是依赖固件构建和主机回归的构建目标，其名称不表示已经完成实板验收或正式发布。默认源码归档为 `development` 模式；固定提交的正式候选要求见[候选包来源](../CONTRIBUTING.zh-CN.md#候选包来源)。

## 构建产物与校验

以下路径均相对于 `build/bes2700yp/main/`：

| 产物 | 用途 |
|---|---|
| `zephyr.bin` | 用于整包刷写的完整镜像，`release/zephyr.bin` 保存同一镜像 |
| `release/layout.json` | 镜像布局及日志验收所需参数 |
| `release/offline-validation.json` | 离线审计结果 |
| `release/manifest.json` | 镜像身份、构建配置及验证状态 |
| `release/source-provenance.json` | 集成源码与 HAL 模块的来源记录 |
| `release/integration-source.tar`、`release/hal-consumer.tar` | 集成源码与 HAL 模块归档 |
| `release/SHA256SUMS` | 包内文件的 SHA256 校验清单 |

`release/` 还包含 ELF、map、配置、DTS 和日志解析脚本。`bth/zephyr/zephyr.bin` 和 `m55/zephyr/zephyr.bin` 是单核产物，不能替代本项目整包刷写使用的完整镜像。

从工作区根目录执行包内校验；括号内命令结束后仍位于工作区根目录：

```sh
(
  cd build/bes2700yp/main/release || exit 1
  sha256sum -c SHA256SUMS
)
```

所有条目均应显示 `OK`，命令退出状态应为 0。该检查验证包内文件与清单一致，实板验收另按[测试说明](testing.zh-CN.md)执行。

`build/` 可以整体清空后重建，日志也会删除。清理前将需要保留的镜像、校验清单、报告及实板日志复制到构建目录之外。

## 刷写边界

建议使用 BES 官方刷机工具 **DldProductLine**，刷写构建生成的完整镜像 `build/bes2700yp/main/zephyr.bin`。

本仓尚未提供 `west flash` runner。DldProductLine 的配置参数和板卡连接方式尚未形成完整说明，使用时请遵循目标板对应的官方操作流程。运行地址不能直接作为刷写地址。

开始刷写前须已取得目标板的供电、串口和下载连接资料，以及适用的 DldProductLine 版本和配置；板卡支持范围及当前缺少的连接信息见[硬件说明](hardware/bes2700yp.zh-CN.md#板卡与构建目标)。不能仅凭构建成功判断实体板卡已具备刷写条件。刷写后保存串口日志，使用该镜像对应的 `release/layout.json` 和 `release/` 中的解析脚本验收，具体要求见[测试说明](testing.zh-CN.md)。

## 后续开发

新终端无需重新安装工具链或创建 venv，恢复工作目录和环境即可。下面使用本文默认安装位置；自定义目录时修改对应路径：

```sh
cd "$HOME/bestechnic-workspace"
export BES_TOOLCHAIN_ROOT="$HOME/toolchains/gcc-arm-none-eabi-10.3-2021.10"
export CROSS_COMPILE="$BES_TOOLCHAIN_ROOT/bin/arm-none-eabi-"
unset TOOLCHAIN_ROOT
export ZEPHYR_BASE="$PWD/zephyr"
```

`west update` 只同步 manifest 中列出的依赖，不更新集成仓自身。需要取得新的 `main` 时，先确认集成仓工作区干净，并将已有的 HAL 本地修改保存到自己的分支，再执行：

```sh
git -C bestechnic-zephyr switch main
git -C bestechnic-zephyr pull --ff-only origin main
.venv/bin/python -m west update
.venv/bin/python -m pip install -r bestechnic-zephyr/requirements.txt
.venv/bin/python -m west blobs fetch hal_bestechnic
.venv/bin/python bestechnic-zephyr/scripts/check_repo.py
```

随后按[构建](#构建)执行干净构建。HAL 随 manifest 同步到匹配版本，不需要单独追踪 HAL 仓库的 `main`。
