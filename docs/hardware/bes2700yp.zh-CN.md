# BES2700YP 硬件与支持范围

[English](bes2700yp.md)

## 芯片资源概览

以下概览依据 BES 官方 [BES2700YP 产品页面](https://www.bestechnic.com/en/article/78/64.html)和[简版数据手册](https://www.bestechnic.com/Uploads/keditor/file/20241010/20241010185852_50097.pdf)整理。它描述芯片资源，当前工程使用的资源及其支持范围见下文。

| 类别 | 官方公开资源 |
|---|---|
| 主处理子系统 | Arm Cortex-M55，配有指令和数据 TCM、cache |
| Bluetooth Host 子系统（BTH） | STAR-MC1 |
| Sensor Hub 子系统 | STAR-MC1、传感器引擎、BECO NPU |
| 存储 | 共享 4 MB SRAM、封装内 Flash、启动 ROM |
| 蓝牙 | 双模 Bluetooth 5.3，支持 LE Audio |
| 音频 | 2 路 DAC、4 路 ADC，以及 ANC、EQ 等处理模块 |
| 外设接口 | GPADC、SPI、I²C、UART、I²S、TDM、SPDIF、DMIC、PWM、GPIO 等 |
| 安全资源 | 安全引擎、TRNG、eFuse |
| 系统资源 | DMA、定时器、看门狗、JTAG/SWD 等 |

共享 SRAM 总容量不等于任一 Zephyr 内核可使用的容量，本工程的分配见[运行内存布局](#运行内存布局)。官方摘要未明确 Flash 容量、最高主频和各外设实例数量，此处不作推定；具体型号规格以 BES 对应资料为准。

## 板卡与构建目标

本项目使用 BES2700YP 的 BTH 和 M55 两个子系统，分别运行独立的 Zephyr 内核。板级目标如下：

| 子系统 | 处理器 | 构建目标 |
|---|---|---|
| BTH | STAR-MC1 | `bes2700yp_devkit/bes2700yp/bth` |
| M55 | Cortex-M55 | `bes2700yp_devkit/bes2700yp/cm55` |

完整镜像从 BTH 目标启动 sysbuild，M55 作为子镜像构建；单独构建 M55 目标不会生成可直接刷写的完整镜像。

BTH 的官方处理器名称为 STAR-MC1，当前 Zephyr 移植使用 Cortex-M33 目标配置，见 [SoC Kconfig](../../bsp/soc/bestechnic/bes2700yp/Kconfig)和 [BTH DTS](../../bsp/dts/arm/bestechnic/bes2700yp_bth.dtsi)。芯片名称和软件目标配置分别描述硬件与移植实现。

`bes2700yp_devkit` 是本项目的板级目标名，不能仅凭该名称判断实体板卡兼容性。板级文件中的 `V05` 字样也不作为实体板卡修订号的依据。当前适配范围限于 BES2700YP，其他 BES2700/BES2800 型号需单独适配与验证。

当前仓库尚未记录以下硬件信息，接线和刷写前需从目标板官方资料或板卡提供方确认：

| 项目 | 需要确认的信息 |
|---|---|
| 板卡身份 | 完整型号、料号、PCB 丝印和硬件修订 |
| 供电 | 供电接口、电压及供电方式 |
| 串口连接 | 接口位置、TX/RX/GND 引脚和逻辑电平 |
| 下载连接 | 下载接口、连接方式和进入下载模式的操作 |

维护者补充这些资料时，应记录资料对应的板卡版本和来源，并更新本节说明。实板报告也记录同一板卡身份，避免将一个修订版的接线或测试结论直接用于另一块板。

取得板卡接线和下载模式资料后，按[刷写边界](../getting-started.zh-CN.md#刷写边界)使用 BES 官方 DldProductLine 刷写完整镜像。

## 当前支持范围

以下按当前代码及 `main` 默认双核应用说明接入情况。“已接入”描述实现范围，实板验证结论需另行核对对应镜像的测试记录。芯片公开资源与接入状态的简表见 [README](../../README.zh-CN.md#当前适配状态)。

### 已接入的功能与默认配置

| 功能 | 实现与接口 | 默认应用状态 | 当前限制 |
|---|---|---|---|
| 双核启动与基础内核 | bootstrap 启动 BTH，由 BTH 装载并启动 M55；两核使用 Zephyr 线程、计时和同步机制，见[启动流程](../architecture.zh-CN.md#启动流程) | 启用，两核分别运行独立内核 | 不使用 Zephyr SMP；启动依赖匹配的 HAL 模块 |
| 核间通知 | [mailbox 驱动](../../bsp/drivers/mbox/mbox_bes2700.c)接入 Zephyr MBOX API | 两核均启用 `CONFIG_MBOX` 和 `CONFIG_MBOX_BES2700` | 仅传递通知，不携带消息内容；忙时重复发送合并为一次待发通知 |
| 共享内存消息 | [消息 worker](../../platforms/bes2700yp/ipc/worker.c)在共享区收发消息，配合 mailbox 通知 | 启用双向消息收发 | 使用本项目协议，尚未接入 Zephyr IPC service / RPMsg |
| BTH UART | [UART 驱动](../../bsp/drivers/serial/uart_bes2700.c)实现轮询和中断 API | 未启用 Zephyr Serial/Console；当前日志使用 bootstrap 串口接口 | 固定 8N1，依赖 bootstrap 准备时钟与引脚；未提供异步/DMA API 或运行时串口参数配置 |
| 系统计时与时钟 | Zephyr Cortex-M SysTick，HAL 完成启动时钟配置 | 两核均配置为 24 MHz，内核每秒 1000 tick；`CONFIG_TICKLESS_KERNEL=n`、`CONFIG_PM=n` | 24 MHz 是工程配置，不表示芯片最高主频；未集成动态调频与 Zephyr 系统低功耗管理 |
| FPU / MPU | [SoC 配置](../../bsp/soc/bestechnic/bes2700yp/Kconfig)声明硬件能力，M55 提供 [MPU 区域定义](../../bsp/soc/bestechnic/bes2700yp/mpu_regions.c) | 两核应用均设置 `CONFIG_FPU=n`、`CONFIG_ARM_MPU=n`、`CONFIG_HW_STACK_PROTECTION=n` | 默认应用不覆盖这些功能，启用后的运行验证需单独完成 |
| 启动与运行内存 | DTS/链接脚本定义运行布局，bootstrap 使用 HAL 初始化硬件；见[架构说明](../architecture.zh-CN.md) | 使用当前[运行内存布局](#运行内存布局) | 启动和装载依赖匹配的 HAL 模块及内存布局 |
| M55 正常重启 | 可选 `m55-restart` 场景保留 RAM，由 BTH 停止并重启 M55 | 默认场景不启用；新候选待实板验证 | 仅覆盖协作停止；见[重启契约](../m55-restart.zh-CN.md) |

mailbox 使用硬件通道 1，对 Zephyr 客户端暴露逻辑通道 0；硬件通道 0 保留给厂商 loader，见 [mailbox 绑定](../../bsp/dts/bindings/mbox/bestechnic,bes2700-mbox.yaml)。共享内存消息协议负责传递和校验数据，通知次数不等于消息条数。

UART 驱动当前仅适用于 BTH。默认 BTH UART 设备节点未启用，两核均关闭 Zephyr Serial/Console；能看到启动或运行日志，并不表示该驱动或 Console 已在当前应用中启用。日志路径见[串口与日志](#串口与日志)。

### 尚未接入的芯片资源

下表描述本仓尚未提供的 BES2700YP 适配，与 Zephyr 上游是否具有相应子系统无关。

| 芯片资源 | 本仓当前范围 |
|---|---|
| 蓝牙 / LE Audio | 尚未接入控制器/HCI、蓝牙协议栈与音频业务 |
| 音频 | 尚未接入 ADC/DAC、I²S/TDM/SPDIF/DMIC、ANC/EQ 等音频路径 |
| Sensor Hub / BECO NPU | 尚未包含该子系统的启动、Zephyr 目标或 NPU 运行接口 |
| Flash 读写 | HAL 支持启动所需的 Flash 操作；尚未提供 Zephyr Flash 驱动或应用可用的标准读写接口 |
| GPIO、I²C、SPI、PWM、GPADC、DMA、看门狗 | 尚未提供对应的 BES2700YP Zephyr 驱动 |
| 安全资源 | 尚未集成安全引擎、TRNG、eFuse 或安全启动验证；当前镜像 CRC 检查仅用于完整性校验 |

### 配置与验证依据

默认应用配置见 [BTH prj.conf](../../apps/bes2700yp/bth/prj.conf)和 [M55 prj.conf](../../apps/bes2700yp/m55/prj.conf)。应用配置会覆盖板级默认值；例如 M55 板级启用 FPU/MPU，而当前应用将其关闭。判断具体镜像启用的功能时，应核对构建输出的 `release/bth.config`、`release/m55.config` 及实际构建生成的 DTS。

仓库包含 [mailbox 模型回归](../../tests/host/test_mbox_bes2700.py)、[UART 模型回归](../../tests/host/test_uart_bes2700.py)和[消息 worker 回归](../../tests/host/test_message_workers.py)，用于检查主机可模拟的行为。构建与离线审计检查固件生成、装载布局和包内一致性，均不能替代实板验收。

构建包在打包时记录 `hardware: not_tested`；后续实板结果通过独立报告关联镜像 SHA256，不沿用其他镜像的结论，也不改写原包。验证方法、结果入口和证据要求见[测试与发布验证](../testing.zh-CN.md)。

## 串口与日志

| 参数 | 设置 |
|---|---|
| 波特率 | `1152000`（1.152 Mbaud） |
| 数据位 | 8 |
| 校验 | 无 |
| 停止位 | 1 |
| 流控 | 关闭硬件和软件流控 |

bootstrap 和当前 BTH 应用通过 BTH UART 输出启动及运行日志。M55 状态由 BTH 读取并报告，默认未启用独立的 M55 串口控制台。参数与实现分别见[启动契约](../../platforms/bes2700yp/boot/bootstrap/bth_contract.h)和 [BTH 应用](../../apps/bes2700yp/bth/src/main.c)。

物理接线需按上文确认的板卡信息进行，不能根据芯片引脚复用代码推定板卡连接器的引脚。完整日志的采集和验收要求见[测试说明](../testing.zh-CN.md)。

## 运行内存布局

以下是当前 `main` 双核应用的主要运行区域，长度以 KiB（1024 字节）计：

| 区域 | 起始地址 | 长度 |
|---|---|---:|
| BTH 向量及代码区 | `0x00510000` | 192 KiB |
| BTH 数据区 | `0x20540000` | 112 KiB |
| M55 向量及代码区 | `0x000a0000` | 256 KiB |
| M55 应用数据区 | `0x200c0000` | 624 KiB |
| 双核消息共享区 | `0x2015c000` | 8 KiB |

BTH 区域由 [BTH DTS](../../bsp/dts/arm/bestechnic/bes2700yp_bth.dtsi)和[启动契约](../../platforms/bes2700yp/boot/bootstrap/bth_contract.h)约定。M55 的[基础 DTS](../../bsp/dts/arm/bestechnic/bes2700yp_cm55.dtsi)将数据区设为 632 KiB，当前应用通过 [overlay](../../apps/bes2700yp/m55/app.overlay)缩减为 624 KiB，为消息共享区预留 8 KiB。

表中代码区位于运行内存，由启动流程装载；板级 DTS 中的 `zephyr,flash` 选择用于链接布局，不能据此将这些区域当成物理 Flash。表格未列出全部启动、诊断和服务保留区，完整分配以实际构建生成的 DTS、链接结果和 `release/offline-validation.json` 为准，相关检查见[离线审计范围](../architecture.zh-CN.md#离线审计范围)。

以上均为运行地址，不能直接作为刷写地址。
