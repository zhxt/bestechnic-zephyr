# bestechnic-zephyr

[English](README.md)

本项目为 BES2700YP 提供双核 Zephyr 集成，BTH（STAR-MC1）和 M55（Cortex-M55）分别运行独立的 Zephyr 内核，通过共享内存和 mailbox 进行核间通信。工程包含板级支持、启动程序和双核通信验证应用，一次 sysbuild 构建即可生成完整刷写镜像 `zephyr.bin`。

## 方案概览

本工程以 `bes2700yp_devkit` 为板级目标名，包含以下两个 Zephyr 构建目标：

| 核 | 硬件处理器 | Zephyr 板级目标 |
|---|---|---|
| BTH | STAR-MC1 | `bes2700yp_devkit/bes2700yp/bth` |
| M55 | Cortex-M55 | `bes2700yp_devkit/bes2700yp/cm55` |

BTH 当前的 Zephyr 移植使用 Cortex-M33 目标配置构建，其硬件处理器为 STAR-MC1。

**构建方式：**以 BTH 板级目标作为 sysbuild 入口，M55 作为子镜像自动构建。一次构建完成两核应用和 `bootstrap` 启动程序的编译，并结合 BES HAL 静态库生成完整刷写镜像 `zephyr.bin`。

**启动流程：**`bootstrap` 在 BTH 核上通过 BES HAL 完成早期硬件初始化，装载并启动 BTH Zephyr；随后由 BTH 应用装载并启动 M55 Zephyr。

芯片资源与开发板信息见[硬件说明](docs/hardware/bes2700yp.zh-CN.md)，启动、镜像封装及核间通信的实现细节见[架构说明](docs/architecture.zh-CN.md)。

## 当前适配状态

当前已集成 BTH/M55 双核启动、基础内核运行和核间消息通信。下表概述芯片公开能力与本项目当前代码的适配范围。

芯片公开能力依据 BES [产品页面](https://www.bestechnic.com/en/article/78/64.html)和[简版数据手册](https://www.bestechnic.com/Uploads/keditor/file/20241010/20241010185852_50097.pdf)，不代表官方 SDK 的完整功能清单。

| 功能 | 芯片公开能力 | 本项目适配状态 |
|---|---|---|
| 处理器与系统 | Cortex-M55、BTH STAR-MC1 | 已集成两个独立 Zephyr 内核，包含启动、共享内存消息和 mailbox 通知 |
| M55 故障隔离 | 双核生命周期 | 可选 READY 超时/心跳停止注入场景；BTH 隔离 M55 并继续监测，不自动重载 |
| M55 故障恢复 | 双核生命周期 | 可选单次恢复场景；重建 BTH worker、重载 M55 并验证新会话通信 |
| UART | UART 外设 | 已实现 BTH 轮询和中断驱动；默认未启用 Zephyr Serial/Console，日志通过 bootstrap 串口输出 |
| 存储与 Flash | SRAM、封装内 Flash、启动 ROM | 已配置运行内存布局及 HAL 启动支持；尚未提供 Zephyr Flash 驱动 |
| 蓝牙 | 双模 Bluetooth 5.3、LE Audio | 尚未接入 |
| 音频 | ADC/DAC、音频接口、ANC/EQ 等 | 尚未接入 |
| Sensor Hub / NPU | STAR-MC1、传感器引擎、BECO NPU | 尚未接入 |
| 通用外设 | GPIO、I²C、SPI、PWM、GPADC、DMA、看门狗等 | 尚未提供对应的 BES2700YP Zephyr 适配 |
| 时钟与低功耗 | 时钟及电源管理资源 | 使用 HAL 完成启动配置，两核当前配置为 24 MHz；尚未集成 Zephyr 系统低功耗管理 |

默认配置、驱动接口及使用限制见[当前支持范围](docs/hardware/bes2700yp.zh-CN.md#当前支持范围)，实板验证方法见[测试说明](docs/testing.zh-CN.md#实板验收)。

## 开始使用

构建依赖 Bestechnic HAL 模块（`hal_bestechnic`）提供的预编译静态库。集成仓通过 `west init` 获取，HAL 模块与其他依赖通过 `west update` 按固定提交同步，静态库通过 `west blobs fetch hal_bestechnic` 获取，正常构建无需完整 BES SDK。HAL 版本匹配要求见 [HAL 说明](docs/hal.zh-CN.md)。

首次使用，请按[环境准备与构建](docs/getting-started.zh-CN.md)完成主机依赖安装、Python 虚拟环境创建和 `main` 分支工作区初始化。仓库地址及远程同步前提见[工作区说明](docs/getting-started.zh-CN.md#工作区)。

工具链使用 GNU Arm Embedded **10.3-2021.10**（[Linux x86_64 下载](https://developer.arm.com/-/media/Files/downloads/gnu-rm/10.3-2021.10/gcc-arm-none-eabi-10.3-2021.10-x86_64-linux.tar.bz2)），下载与解压命令见[工具链安装](docs/getting-started.zh-CN.md#工具链安装)。下面采用该步骤的默认安装位置；使用其他位置时修改 `BES_TOOLCHAIN_ROOT`。

完成上述准备后，在包含 `.venv/`、`zephyr/` 和 `bestechnic-zephyr/` 的工作区根目录执行以下命令，使用 `main` 分支默认配置进行干净构建：

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

完整镜像位于 `build/bes2700yp/main/zephyr.bin`，同目录的 `release/` 保存配套发布文件，详见[构建产物与校验](docs/getting-started.zh-CN.md#构建产物与校验)。

建议使用 BES 官方刷机工具 **DldProductLine** 刷写生成的完整镜像。板卡连接和工具配置请遵循[刷写要求](docs/getting-started.zh-CN.md#刷写边界)，刷写后按[测试说明](docs/testing.zh-CN.md#实板验收)采集日志并验收。

## 文档

- [环境准备与构建](docs/getting-started.zh-CN.md)
- [BES2700YP 硬件与支持范围](docs/hardware/bes2700yp.zh-CN.md)
- [测试与发布验证](docs/testing.zh-CN.md)
- [M55 正常重启验证](docs/m55-restart.zh-CN.md)
- [架构与代码归属](docs/architecture.zh-CN.md)
- [Bestechnic HAL 模块](docs/hal.zh-CN.md)
- [贡献指南](CONTRIBUTING.zh-CN.md)
- [来源与许可范围](THIRD_PARTY_NOTICES.zh-CN.md)

## 许可

具有 Apache-2.0 SPDX 标识的文件使用仓库 [LICENSE](LICENSE)。独立 HAL 模块中的厂商制品适用其各自说明，来源与许可范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.zh-CN.md)。
