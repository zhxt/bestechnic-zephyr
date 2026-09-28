# 架构与代码归属

[English](architecture.md)

BES2700YP 的 BTH（STAR-MC1）和 M55（Cortex-M55）分别运行独立的 Zephyr 内核，两核使用同一固定版本的 Zephyr 源码构建。消息内容存放在共享内存中，mailbox 用于通知对端处理。

芯片资源和板级目标见[硬件说明](hardware/bes2700yp.zh-CN.md#板卡与构建目标)。

## 系统组成

bootstrap 在 BTH 核上完成早期硬件初始化，装载并启动 BTH Zephyr；BTH 随后校验、装载并启动 M55 Zephyr。bootstrap 链接 BES HAL 静态库，并在交接后保留供 BTH 调用的硬件服务入口。两核通过公共接口和共享内存协议协作，不互相包含应用私有目录。

## 构建流程

一次 sysbuild 构建按以下顺序生成完整镜像：

```text
M55 ELF
  → m55.segment.bin 和 m55_payload.h
  → BTH ELF（包含 M55 镜像）
  → bth.payload.bin
  → bootstrap + HAL 静态库 → adapter.elf
  → 镜像封装与离线审计 → zephyr.bin
```

`m55.segment.bin` 记录 M55 各段的目标地址、数据位置和长度，`m55_payload.h` 将其嵌入 BTH 并提供校验信息。`bth.payload.bin` 带有供 bootstrap 装载 BTH 的入口和校验信息。最终的 `zephyr.bin` 是完整刷写镜像。

构建依赖由 [sysbuild/dual.cmake](../sysbuild/dual.cmake)组织；[M55 打包脚本](../scripts/pack_m55_payload.py)、[BTH 打包脚本](../scripts/pack_bth_payload.py)和[固件构建脚本](../scripts/firmware.py)分别处理镜像生成与审计。构建命令见[环境准备与构建](getting-started.zh-CN.md#构建)，中间产物写入构建目录。

## 启动流程

当前默认应用在完成有限时长的通信验证后由 BTH 停止 M55。可选的 `m55-restart` 场景保持 BTH 运行，正常停止并重启 M55 十次；见[测试说明](testing.zh-CN.md#专项验证配置)与[重启契约](m55-restart.zh-CN.md)。

1. bootstrap 在 BTH 核上完成早期硬件初始化，检查 BTH payload，将其复制到目标内存并核对校验值。
2. bootstrap 建立硬件服务入口，准备中断和处理器状态，然后交接到 BTH Zephyr。
3. BTH 检查服务接口及内嵌的 M55 镜像，调用硬件服务准备 M55 时钟和内存，并让 M55 暂停在等待程序中。
4. BTH 将 M55 镜像各段写入目标内存，校验复制结果，再通过硬件服务启动 M55。
5. M55 进入自己的 Zephyr 内核和应用。BTH 检查对端状态，两核通过共享内存传递消息，并以 mailbox 中断通知对端。

BTH 装载与交接见 [bootstrap/adapter.c](../platforms/bes2700yp/boot/bootstrap/adapter.c)；M55 装载及状态检查见 [BTH 应用](../apps/bes2700yp/bth/src/main.c)。运行内存范围见[硬件说明](hardware/bes2700yp.zh-CN.md#运行内存布局)。

## HAL 与硬件服务边界

HAL 静态库只链接 bootstrap，BTH 和 M55 的 Zephyr 镜像不直接链接这些库。交接后，BTH 通过保留的服务入口调用 M55 时钟、内存和启动控制等操作；服务代码仍在 BTH 核上执行，接口见 [dual_service.c](../platforms/bes2700yp/boot/bootstrap/dual_service.c)。`adapter` 是 bootstrap 源码及产物使用的名称，不代表另一个独立内核。

### 资源服务扩展设计

[只读服务](hal.zh-CN.md#只读资源服务)实现能力发现和系统快照。
描述符链接到 bootstrap `.rodata`，请求使用调用方拥有的 BTH 应用 RAM，
保留原服务和诊断内存布局。以下契约也适用于后续修改硬件状态的资源操作。

资源服务设计沿用库边界：Zephyr 驱动 → BTH 资源客户端 → bootstrap 常驻资源服务 →
受限 HAL 小接口。UART/GPIO 数据收发和 ISR 留在 Zephyr 驱动中，只有共享硬件配置
经此桥接。[接口设计](hal.zh-CN.md#运行期资源接口设计)定义能力、调用上下文、所有权
和失败语义。

保留现有 32 字节 `dual_service` 描述符与生命周期操作语义，通过显式发现操作获取
独立版本的资源描述符和 dispatch，不复用 STOP、PREPARE 或快照缓冲区。服务发现不依赖
对端生命周期阶段。资源驱动启用后，能力缺失或不兼容须在改硬件前失败，不能悄悄回退到
全域初始化。

ABI 使用固定宽度整数，检查请求长度、保留字段、对齐和完整地址范围。缓冲区属于 BTH，
在同步调用期间有效；拒绝地址计算溢出或越出允许内存的请求。不跨 ABI 传递 Zephyr
结构体、浮点值、回调、堆所有权或厂商 ID。描述符存储位置和 Thumb 入口须落在常驻且有
文件内容支撑的 ELF 段中，启用前评审 kernel/bootstrap 调用约定、栈占用及实际指令。
描述符或临时存储显式纳入链接/资源契约和审计，不将诊断区看似空白的位置直接当作空闲。

设计中的代码职责分配为：`platforms/bes2700yp/resources/` 承载 BTH 客户端与仲裁，
`platforms/bes2700yp/boot/bootstrap/` 承载常驻后端，
`include/bestechnic/bes2700yp/` 定义项目公共契约。Zephyr 驱动及 binding 放在 `bsp/`，
厂商实现保留在 HAL 生成仓，不向两个内核加入厂商私有头文件或另一份 HAL。
M55 资源服务须有独立的 IPC 协议与权限契约。运行期契约和源码纳入固件构建输入，
独立审计策略不能替代运行期授权。

## 目录职责

| 目录 | 责任 |
|---|---|
| [apps/bes2700yp/bth](../apps/bes2700yp/bth) | BTH 应用及构建配置 |
| [apps/bes2700yp/m55](../apps/bes2700yp/m55) | M55 应用及构建配置 |
| [bsp/](../bsp) | 板卡、SoC、DTS 和驱动 |
| [platforms/bes2700yp/boot/bootstrap](../platforms/bes2700yp/boot/bootstrap) | BTH 启动交接、硬件服务和诊断 |
| [platforms/bes2700yp/lifecycle](../platforms/bes2700yp/lifecycle)、[platforms/bes2700yp/resources.json](../platforms/bes2700yp/resources.json) | M55 重启管理器与资源契约 |
| [platforms/bes2700yp/ipc](../platforms/bes2700yp/ipc)、[include/bestechnic/bes2700yp](../include/bestechnic/bes2700yp) | 核间消息实现、公共接口及共享内存布局 |
| [sysbuild/](../sysbuild)、[scripts/](../scripts) | 多镜像构建、打包、审计、日志分析及源码归档 |
| [tests/](../tests) | 主机回归和构建检查 |

[Zephyr 模块声明](../zephyr/module.yml)注册本仓的板卡、SoC 和 DTS 路径；驱动通过根目录的 [Kconfig](../Kconfig) 和 [CMakeLists.txt](../CMakeLists.txt)接入。本仓不修改 Zephyr 的 kernel/arch。

## 构建标识与来源记录

[scripts/project_files.json](../scripts/project_files.json) 的 `build` 清单选择参与固件标识计算的源码和配置文件。文件内容哈希与构建参数、工具链版本、模块提交及 HAL manifest 哈希共同生成构建输入摘要。文档、测试和编辑器文件不在该清单中，但仍可包含在源码归档中。

Git 提交与源码归档记录来源；构建输入摘要及派生标识用于检查构建和两核匹配；完整镜像 SHA256 核对最终文件。`validation_profile` 选择验证应用的测试参数，`profile_id` 则匹配启动诊断日志。下表路径相对于构建目录，例如 `build/bes2700yp/main/`：

| 信息 | 用途与记录位置 |
|---|---|
| Git 提交与工作区状态 | 记录集成仓和 HAL 模块来源，位于 `release/source-provenance.json`，并汇总到 `release/manifest.json` |
| 验证场景（`validation_profile`） | 描述验证应用行为，记录于 identity、layout 和 manifest |
| 构建输入摘要（`source_sha256`） | 标识参与构建的输入组合，位于 `generated/identity.json` 和 `release/manifest.json` |
| BTH 构建标识（`build`） | 根据装载契约、镜像内容及构建输入生成，写入 BTH payload，记录于 `release/layout.json` |
| M55 构建标识（`m55_build`） | 从构建输入摘要派生，供 BTH 检查 M55 状态，记录于 identity 和 layout |
| 两核匹配标识（`pair`） | 从构建输入摘要派生，写入两核配置；在 `release/layout.json` 中名为 `message_pair` |
| 启动诊断标识（`profile`） | 从构建输入摘要派生；在 `release/layout.json` 中名为 `profile_id` |
| 完整镜像 SHA256 | 记录于 `release/manifest.json` 的 `firmware_sha256` 及 `release/SHA256SUMS` |

未提交修改无法仅凭 Git 提交号确定；构建包保存源码归档与文件哈希，正式候选的固定提交要求见[候选包来源](../CONTRIBUTING.zh-CN.md#候选包来源)。

## 离线审计范围

生成完整镜像时，[firmware.py](../scripts/firmware.py)调用[布局检查](../scripts/check_bth_layout.py)和[双核审计](../scripts/audit_dual.py)，并检查：

- 镜像完整性：M55 镜像、BTH payload 与对应构建产物一致，入口和校验信息符合装载要求。
- 内存布局：装载段位于各核分配区域内，不覆盖共享内存、启动服务和诊断保留区。
- 两核配置：mailbox 中断绑定、DTS、通信参数和 `pair` 标识符合约定。
- 早期 RAM 放置：Flash 初始化所需代码和状态位于早期 RAM 段，关键启动函数位于预期区间。
- 启动代码基准：`bth_crc32` 和 `bth_copy_bytes` 的机器码哈希与 [t2-machine-code.json](../platforms/bes2700yp/boot/t2-machine-code.json) 中的基准一致，并检查启动路径中的调用次数。
- `m55-restart` 场景：保留控制区、复位诊断、SRAM 计时函数、REPARK 服务及可执行服务入口满足[重启契约](m55-restart.zh-CN.md)。

审计结果写入 `release/offline-validation.json`。布局或关键启动代码变化时，需同步检查接口约定、审计规则及回归验证。离线审计不能代替实际启动、通信和持续运行的[实板测试](testing.zh-CN.md)。
