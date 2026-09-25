# 测试与发布验证

[English](testing.md)

先按[环境准备与构建](getting-started.zh-CN.md)准备工作区、匹配的 HAL 模块和工具链。本文命令从包含 `bestechnic-zephyr/`、`.venv/` 和 `zephyr/` 的工作区根目录执行；构建命令沿用环境说明中的 `ZEPHYR_BASE` 和 `CROSS_COMPILE`。

下表列出验证流程及结果入口，各阶段的结果分别保存，发布准备由维护者执行：

| 阶段 | 验证内容 | 结果入口 |
|---|---|---|
| 仓库检查 | 文件范围、`west.yml` 与 `module-lock.json` 的一致性、文档链接目标文件及 HAL 文件哈希 | `check_repo.py` 输出 |
| 主机回归 | 在主机执行协议、驱动模型、日志解析和打包回归 | `test_host.py` 输出及退出码 |
| 构建与离线审计 | 固件生成、装载布局、镜像匹配及包内校验 | 构建日志、`release/offline-validation.json`、`release/SHA256SUMS` |
| 实板验收 | 目标板的启动、双核运行和消息行为 | 原始串口日志、包内解析器报告及操作记录 |
| 发布准备（维护者） | 固定来源、证据归档及如实标注分发状态 | [贡献指南：分支与发布](../CONTRIBUTING.zh-CN.md#分支与发布) |

## 仓库检查与主机回归

```sh
.venv/bin/python bestechnic-zephyr/scripts/check_repo.py
.venv/bin/python bestechnic-zephyr/scripts/test_host.py
```

仓库检查应返回 `status: pass` 且 `issues` 为空。`publication_pending` 单独报告尚未确认的 HAL 公开再分发依据、HAL 的 `public_source_url` 字段未填写，以及集成仓和 HAL 的干净提交与远端配置缺口。`--for-publication` 要求干净提交和已配置的远端，但不会把 `unconfirmed` 状态视为已获授权。

主机回归覆盖实际消息收发代码、协议校验、快照抢占、mailbox/UART 模型、日志解析、镜像打包负例和文件/归档边界。预期输出 `OK`，退出码为 0。主机模型验证不能替代目标板上的运行验证。

## 构建验证

普通开发按[构建说明](getting-started.zh-CN.md#构建)使用 `main` 默认配置，构建目录为 `build/bes2700yp/main`。构建成功后检查离线审计和[包内校验](getting-started.zh-CN.md#构建产物与校验)；它们不能代替实板验收。离线审计项目见[架构说明](architecture.zh-CN.md#离线审计范围)。

### CI 入口

[scripts/ci.py](../scripts/ci.py)可在本地主机或 CI 中执行。以下命令只进行仓库检查和主机回归：

```sh
.venv/bin/python bestechnic-zephyr/scripts/ci.py \
  --workspace . --output build/ci-host
```

需要同时构建专项配置时，显式选择配置并传入工具链前缀：

```sh
.venv/bin/python bestechnic-zephyr/scripts/ci.py \
  --workspace . --output build/ci-matrix \
  --profiles ipc-sequential ipc-backpressure ipc-fault-injection ipc-backpressure-1h \
  --cross-compile "${CROSS_COMPILE:?Set up the toolchain first}"
```

`--output` 必须是源码仓库之外、尚不存在的目录，重复执行时使用新目录。脚本接受下表四种场景；未指定 `--profiles` 时只执行仓库和主机检查，不构建固件。上例构建全部四种场景，但不进行实板验收。

输出目录包含 `summary.json`、`repository.log`、`host.log`，以及所选配置的构建日志和构建目录。预期汇总 `status` 为 `pass`、各项 `exit_code` 为 0；所构建包的 `SHA256SUMS` 也会被核对。脚本不操作硬件，汇总中的 `hardware` 保持 `not_tested`。正式候选可追加 `--formal`，要求见[候选包来源](../CONTRIBUTING.zh-CN.md#候选包来源)。

## 专项验证配置

四种验证场景是 `BES_VALIDATION_PROFILE` 选择的测试参数组合，不表示源码版本。它们用于针对通信行为执行专项验证，参数定义见[验证场景表](../scripts/validation_profiles.py)，由[固件配置脚本](../scripts/firmware.py)生成两核配置。

默认选择 `ipc-backpressure`，运行 600 秒双向背压通信，BTH 观察至 610 秒后结束验证并停止 M55。当前两核应用用于有限时长的适配验证，`BES_VALIDATION_PROFILE` 是该应用的场景选择入口，业务应用需按自身运行要求配置。

场景通过 `validation_schema=1` 和 `validation_profile` 记录于 `layout.json`，身份文件和发布 manifest 使用构建 schema 3。分析器逐项核对固定参数、两核身份和运行记录，不认识的版本或不匹配的参数会失败。随包提供的 `validation_profiles.py` 是分析器依赖，复制验证包时应完整保留并核对 `SHA256SUMS`。

| 配置 | 消息行为与完成条件 | 心跳观察终点 |
|---|---|---:|
| ipc-sequential | 顺序双向各 10000 条，完成后继续观察心跳 | 600 秒 |
| ipc-backpressure | 双向持续通信 600 秒，覆盖背压和慢消费，结束后核对闭环计数 | 610 秒 |
| ipc-fault-injection | 双端错误注入、错误检测及前后正常通信检查，完成后继续观察心跳 | 600 秒 |
| ipc-backpressure-1h | 双向持续通信 3600 秒，覆盖背压和慢消费，结束后核对闭环计数 | 3610 秒 |

ipc-sequential、ipc-fault-injection 中的 600 秒不是要求消息阶段持续运行的时间。ipc-backpressure、ipc-backpressure-1h 的心跳额外观察 10 秒，以覆盖消息停止和结束状态。实际验收参数从对应包的 `layout.json` 读取。

以下以 ipc-fault-injection 为例；选择其他配置时修改变量，各配置使用独立构建目录：

```sh
BES_TEST_PROFILE=ipc-fault-injection
.venv/bin/python -m west build --sysbuild -p always \
  -b bes2700yp_devkit/bes2700yp/bth \
  bestechnic-zephyr/apps/bes2700yp/bth \
  -d "build/bes2700yp/$BES_TEST_PROFILE" -- \
  -DZEPHYR_TOOLCHAIN_VARIANT=cross-compile \
  -DCROSS_COMPILE="${CROSS_COMPILE:?Set up the toolchain first}" \
  -DBES_VALIDATION_PROFILE="$BES_TEST_PROFILE"
```

`-p always` 会清理所选构建目录。重新构建前，应先保存需要保留的包和验证资料。

## 实板验收

### 保存待测包

为每个候选保存完整 `release/`，后续刷写、解析和复核均使用这一份包。以下示例使用普通构建产物，以 UTC 时间和镜像 SHA256 前 12 位生成候选目录；后续命令在同一终端使用 `BES_TEST_DIR`：

```sh
BES_CANDIDATE="main-$(date -u +%Y%m%dT%H%M%SZ)-$(sha256sum build/bes2700yp/main/release/zephyr.bin | cut -c1-12)"
BES_TEST_DIR="validation/$BES_CANDIDATE"
mkdir -p validation
(
  mkdir "$BES_TEST_DIR" || exit 1
  cp -a build/bes2700yp/main/release "$BES_TEST_DIR/release" || exit 1
  cd "$BES_TEST_DIR/release" || exit 1
  sha256sum -c SHA256SUMS
)
```

所有校验项均应为 `OK`，退出码为 0，再继续刷写。候选目录必须尚不存在；重新构建或改用专项配置时，从对应构建目录重新生成候选名，并在新终端中重新设置 `BES_TEST_DIR` 为已保存的候选目录。

### 刷写与采集

1. 使用 BES 官方 **DldProductLine** 刷写保存的完整 `$BES_TEST_DIR/release/zephyr.bin`，连接与配置遵循[刷写要求](getting-started.zh-CN.md#刷写边界)。
2. 按[串口设置](hardware/bes2700yp.zh-CN.md#串口与日志)配置串口工具：1152000、8N1、关闭硬件和软件流控。使用原始日志保存功能，不添加主机时间戳或额外行前缀，也不筛选、删改记录。
3. 在待测启动发生前开始采集。记录板卡型号、修订、实际刷写文件的 SHA256、操作时间和启动方式；断电上电与复位分别记录。
4. 将第一轮日志保存为 `$BES_TEST_DIR/run-01.log`，从启动记录一直采集到消息和双核运行的最终结果。出现故障时保留完整故障日志，不以截取的成功片段替代。

默认由 BTH 输出两核运行信息。只保存末尾的 `pass` 行无法完成验收，解析器还会检查启动身份、计时、心跳、消息记录及顺序。

开始测试前查看待测包 `layout.json` 的 `duration_seconds`，据此预留心跳观察时间。消息阶段结束后仍可能继续输出心跳，日志应保留到最终双核运行结果，不能仅凭消息结束就停止采集。实际通过情况由下一节的解析器判定。

### 解析与判读

当前双核消息应用使用包内 `analyze_dual_message.py`。它联合检查启动、启动计时、心跳和消息记录。保留完整包，以便加载随包的其他解析模块；解析器和布局文件必须与所刷镜像匹配。

```sh
.venv/bin/python "$BES_TEST_DIR/release/analyze_dual_message.py" \
  "$BES_TEST_DIR/run-01.log" \
  --manifest "$BES_TEST_DIR/release/layout.json" \
  --output "$BES_TEST_DIR/run-01.json"
```

这里 `--manifest` 实际接收 **`layout.json`**，不是 `manifest.json`。解析器依据其中的 BTH/M55 build、profile、pair 及通信参数核对日志，输出 JSON 报告并使用以下退出码：

| 状态 | 退出码 | 含义 |
|---|---:|---|
| `pass` | 0 | 对应启动记录满足解析规则 |
| `fail` | 1 | 检测到错误或不符合约定的记录 |
| `incomplete` | 2 | 缺少完成验收所需的记录 |

顶层 `status` 只表示日志中最后一次启动的结果。检查 `session_count` 和每个 `sessions` 条目的 `status`、`errors`、`missing`，不能用最后一次通过覆盖先前失败或不完整的启动。建议每轮独立保存日志和报告；预期单轮报告只有一个 session，且状态为 `pass`、`errors` 和 `missing` 为空。报告中的计时 warnings 仍需按其提示复核。

正式候选应分别构建并实板验收四种场景。`ipc-sequential`、`ipc-fault-injection` 和 `ipc-backpressure-1h` 各保存至少一次独立启动的完整日志与报告；`ipc-backpressure` 保存三次。顺序消息场景核对双向各 10000 条及后续心跳，错误注入场景核对检测及恢复后的正常通信，一小时场景核对完整持续时间和最终闭环计数。每轮使用 `run-01`、`run-02` 等文件名，并按该包的 `layout.json` 解析。解析器不能证明是否断电，冷启动结论必须同时有操作记录。固件身份变化后，应根据改动范围重新验证并生成对应报告。

### 测试记录

每轮测试保存原始串口日志、解析报告及板卡和启动方式记录，并通过固件 SHA256 关联到完整待测包。汇总实际执行的配置、轮次、通过情况及未完成的验证项。资料保存在构建目录之外，避免重新构建或清理时丢失。

包内 `hardware: not_tested` 表示打包时尚未进行实板测试。后续测试结果记录在独立报告中，保留原包 manifest 和校验清单；新固件身份使用新的测试记录。

## 维护者专项检查

以下工具检查构建依赖传播和构建隔离性，不进行刷写或实板验收。

### 增量构建

[tests/verify_incremental.py](../tests/verify_incremental.py)检查两核源码及 HAL 变更是否正确触发重建，并测试损坏 HAL 的拒绝行为。脚本会临时修改源码和 HAL 文件；仅在无人并发编辑、集成仓与 HAL 均独立复制的工作区运行。使用尚不存在的构建目录：

```sh
.venv/bin/python bestechnic-zephyr/tests/verify_incremental.py \
  --workspace . --build-dir build/verify-incremental \
  --cross-compile "${CROSS_COMPILE:?Set up the toolchain first}"
```

结果见 `build/verify-incremental/incremental-evidence/report.json`。核对 `status: pass`、`changes_restored: true` 及两仓工作区状态；实板验收另用保存的候选包。

### 隔离构建

[scripts/isolate_build.py](../scripts/isolate_build.py)需要 bubblewrap 和可用的非特权用户 namespace。它隐藏外部目录和网络，在只读工作区上进行两次干净构建并比较镜像 SHA256。将 `BES_SDK_DIR` 设为工作区外待隐藏 SDK 目录的绝对路径；工具链可使用[默认安装位置](getting-started.zh-CN.md#工具链安装)，但不能位于该 SDK 目录内。进入隔离环境前须完成 `west blobs fetch hal_bestechnic`。虚拟环境、Git 元数据和符号链接须在隔离环境中可用。

```sh
.venv/bin/python bestechnic-zephyr/scripts/isolate_build.py \
  --workspace . --output build/verify-isolation \
  --cross-compile "${CROSS_COMPILE:?Set up the toolchain first}" \
  --sdk "${BES_SDK_DIR:?Set BES_SDK_DIR to the SDK directory to hide}"
```

输出目录必须尚不存在。构建日志和 `isolation-report.json` 位于该目录中。

若已有同一输入和 `ipc-backpressure` 配置的普通构建，可追加 `--reference-build build/bes2700yp/main`（替换为实际构建目录）。脚本会核对构建标识，并要求普通构建与两次隔离构建的 `zephyr.bin` 完全一致，以检查工具链安装路径等环境差异是否影响镜像。
