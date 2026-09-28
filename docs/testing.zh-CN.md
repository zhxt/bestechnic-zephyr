# 测试与发布验证

[English](testing.md)

先按[环境准备与构建](getting-started.zh-CN.md)准备工作区、匹配的 HAL 模块和工具链。本文命令从包含 `bestechnic-zephyr/`、`.venv/` 和 `zephyr/` 的工作区根目录执行；构建命令沿用环境说明中的 `ZEPHYR_BASE` 和 `CROSS_COMPILE`。

下表列出验证流程及结果入口，各阶段的结果分别保存，发布准备由维护者执行：

| 阶段 | 验证内容 | 结果入口 |
|---|---|---|
| 仓库检查 | 文件范围、`west.yml` 与 `module-lock.json` 的一致性、文档链接目标文件及 HAL 文件哈希 | `check_repo.py` 输出 |
| 主机回归 | 在主机执行协议、驱动模型、日志解析和打包回归 | `test_host.py` 输出及退出码 |
| 构建与离线审计 | 固件生成、装载布局、镜像匹配及包内校验 | 构建日志、`release/offline-validation.json`、`release/SHA256SUMS` |
| 资源所有权 | 生成 DTS/config 的访问边界及冲突 | 包外保存的 `check_resources.py` 报告 |
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

### 资源所有权静态检查

[check_resources.py](../scripts/check_resources.py)读取完整发布包中两核生成的
`bth.dts`、`m55.dts`、`bth.config` 和 `m55.config`：

```sh
.venv/bin/python bestechnic-zephyr/scripts/check_resources.py \
  --release build/bes2700yp/main/release --zephyr-base zephyr \
  --output build/bes2700yp/main-resources.json
```

使用工作区锁定的 Zephyr 提供 DTS 解析器。检查器结合现有运行期资源契约、bootstrap
契约和[审计策略](../scripts/resource_ownership.json)，核对当前双核应用的 CPU
时钟及配置、已启用 MMIO 的使用权、同核 IRQ 范围与冲突、mailbox 字段共享、BTH
代码/数据别名和共享内存保留区。不同核的私有外设地址或 IRQ 数字相同允许通过。
bootstrap UART 及其引脚在 DTS 节点禁用时仍被保留。通用 GPIO/pinctrl 编码、地址
转换及新增 clock/reset/power 依赖需要审查策略，未获准时检查失败。

预期 `status: pass`、`errors: []`，退出码为 0；冲突或输入不可读返回 1，命令行参数
错误返回 2。`unconfirmed` 单独列出尚缺少的板级连接、电平、IRQ 路由及时间基准证据，
静态检查通过不表示这些问题已解决。该检查补充 ELF/物理 RAM bank 审计，不执行运行期
权限控制，也不证明硬件运行正常。

报告记录检查器、策略、契约、解析器及 DTS/config 的哈希，须保存在源码仓和冻结包之外。
契约兼容的既有包可直接检查，保留原始校验清单和实板证据。审计脚本与策略纳入源码归档，
不作为固件配置；工具改动是否需要重新构建或刷板，应依据实际构建输入差异决定。
新的正式候选仍须生成自己的构建及来源记录。

CI 在包内校验之后执行此检查，资源冲突会阻止产物验收。直接执行 `west build`
会运行既有镜像/ELF 审计，资源所有权检查需另外执行上述命令。

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

`--output` 必须是源码仓库之外、尚不存在的目录，重复执行时使用新目录。脚本接受下表全部场景；未指定 `--profiles` 时只执行仓库和主机检查，不构建固件。上例构建四种消息场景，但不进行实板验收；重启场景可单独选择 `--profiles m55-restart`。

输出目录包含 `summary.json`、`repository.log`、`host.log`，以及所选配置的构建日志、构建目录和 `<profile>-resources.json` 资源报告。预期汇总 `status` 为 `pass`、各项 `exit_code` 为 0；所构建包的 `SHA256SUMS` 也会被核对。脚本不操作硬件，汇总中的 `hardware` 保持 `not_tested`。正式候选可追加 `--formal`，要求见[候选包来源](../CONTRIBUTING.zh-CN.md#候选包来源)。

## 专项验证配置

`BES_VALIDATION_PROFILE` 选择验证行为，不表示源码版本。四种消息场景使用原有 IPC ABI；`m55-restart` 使用独立的保留内存生命周期契约。场景参数见[验证场景表](../scripts/validation_profiles.py)，由[固件配置脚本](../scripts/firmware.py)生成两核配置。

默认选择 `ipc-backpressure`，运行 600 秒双向背压通信，BTH 观察至 610 秒后结束验证并停止 M55。当前两核应用用于有限时长的适配验证，`BES_VALIDATION_PROFILE` 是该应用的场景选择入口，业务应用需按自身运行要求配置。

场景通过 `validation_schema=1` 和 `validation_profile` 记录于 `layout.json`，身份文件和发布 manifest 使用构建 schema 3。分析器逐项核对固定参数、两核身份和运行记录，不认识的版本或不匹配的参数会失败。随包提供的 `validation_profiles.py` 是分析器依赖，复制验证包时应完整保留并核对 `SHA256SUMS`。

| 配置 | 消息行为与完成条件 | 心跳观察终点 |
|---|---|---:|
| ipc-sequential | 顺序双向各 10000 条，完成后继续观察心跳 | 至少 600 秒（长范围） |
| ipc-backpressure | 双向持续通信 600 秒，覆盖背压和慢消费，结束后核对闭环计数 | 610 秒 |
| ipc-fault-injection | 双端错误注入、错误检测及前后正常通信检查，完成后继续观察心跳 | 至少 600 秒（长范围） |
| ipc-backpressure-1h | 双向持续通信 3600 秒，覆盖背压和慢消费，结束后核对闭环计数 | 3610 秒 |
| m55-restart | 首次启动 M55 后正常重启十次，每会话双向各 1000 条消息 | 至少 600 秒（长范围） |
| m55-ready-timeout | M55 在 READY 前停止，检测超时并隔离 | 至少 600 秒（长范围） |
| m55-heartbeat-stop | M55 发布十次心跳后停止，检测心跳停滞并隔离 | 至少 600 秒（长范围） |
| m55-ready-recovery | READY 超时隔离后恢复一次，新会话双向各 1000 条消息 | 至少 600 秒（长范围） |
| m55-heartbeat-recovery | 心跳停止隔离后恢复一次，新会话双向各 1000 条消息 | 至少 600 秒（长范围） |
| `m55-ipc-stall-recovery` | 心跳正常、IPC 进度停止后恢复 | 至少 600 秒（长范围） |
| `m55-quiesce-recovery` | QUIESCE 超时后恢复 | 至少 600 秒（长范围） |
| `m55-fatal-recovery` | 有效 fatal 发布后恢复 | 至少 600 秒（长范围） |
| `m55-fatal-unreadable-recovery` | fatal 发布不可读，心跳超时后恢复 | 至少 600 秒（长范围） |
| `m55-repark-failure` | REPARK 前拒绝操作，保持隔离且禁止重试 | 至少 600 秒（长范围） |
| `m55-load-failure` | 装载前拒绝操作，保持隔离且禁止重试 | 至少 600 秒（长范围） |
| `m55-recovery-ready-failure` | 新会话 READY 超时，保持隔离且禁止重试 | 至少 600 秒（长范围） |

ipc-sequential、ipc-fault-injection 中的 600 秒不是要求消息阶段持续运行的时间。ipc-backpressure、ipc-backpressure-1h 的心跳额外观察 10 秒，以覆盖消息停止和结束状态。实际验收参数从对应包的 `layout.json` 读取。

`m55-restart` 的详细要求见[重启契约](m55-restart.zh-CN.md)，使用包内 `analyze_dual_restart.py` 解析；验收需包含 11 次会话及所选范围的完整观察。实板结论以匹配镜像的独立验证报告为准。

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

开始测试前查看待测包 `layout.json` 的 `observation` 与 `duration_seconds`，按计划范围保留日志。消息完成不等于观察结束，实际通过情况由同包分析器判定；默认解析长范围。

### 解析与判读

两个隔离场景使用包内 `analyze_dual_isolation.py`，要求见[故障隔离契约](m55-restart.zh-CN.md#故障隔离场景)。它们保持 M55 复位，不执行自动重载。

恢复场景使用包内 `analyze_dual_recovery.py`，见[一次受控故障恢复](m55-restart.zh-CN.md#一次受控故障恢复)。新会话完成消息和正常停止后，BTH 继续完成观察。

四种消息场景使用包内 `analyze_dual_message.py` 联合检查启动、启动计时、心跳和消息记录。`m55-restart` 使用包内 `analyze_dual_restart.py`，传入相同的 `--manifest` 与 `--output` 参数。保留完整包，以便加载随包的其他解析模块；解析器和布局文件必须与所刷镜像匹配。

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

实板前依据下文矩阵及改动影响固定场景、验收范围和冷启动轮次。发生异常或公共路径变化时追加针对性验证。
每轮关联自己的镜像 SHA256、完整包和报告；物理断电必须有操作记录，解析器不能证明断电。
旧固件的实板证据不直接适用于字节已变化的新镜像。

### 分层观察范围

包内 `observation` 声明支持的范围。十二个生命周期场景及 `ipc-sequential`、
`ipc-fault-injection` 在同一镜像、同一次启动中依次产生：

- `functional`：完成该场景全部操作和消息计数。
- `short`：功能完成后继续观察至少 60 秒，健康样本连续，并完成新的末端状态检查。
- `long`：达到从 monitor 启动起至少 600 秒，同时满足完整短窗口，再次检查末端状态。

生命周期末端确认本地 worker 静止、M55 复位保持和 mailbox 通道 1 标志清理，不访问复位态 DTCM。
消息场景重新读取双向队列的真实状态、guard 和空队列条件，M55 心跳继续运行。
十次正常重启、消息目标和全部十一项协议错误注入保持不变。样本数随实际经过时间确定，不能固定改为 61 条。

使用同包的场景分析器，显式选择短范围：

```sh
.venv/bin/python "$BES_TEST_DIR/release/analyze_dual_recovery.py" \
  "$BES_TEST_DIR/run-01.log" --manifest "$BES_TEST_DIR/release/layout.json" \
  --scope short --output "$BES_TEST_DIR/run-01-short.json"
```

该示例适用于恢复场景；其他场景选用对应的消息、隔离或正常重启分析器。
省略 `--scope` 时默认 `long`；`--scope functional` 用于诊断，不能代替短观察冷启动验收。
`zephyr_observe result` 中 `scope=1` 表示短范围，`scope=2` 表示长范围，但仍须解析完整证据。

报告分别记录 `requested_scope`、`scopes`、`overall_status` 和 `complete`。
短范围 `status: pass` 时，整轮仍可能是 `overall_status: incomplete`、`complete: false`。
固件在短结果后继续监测；长测须继续采集。同一启动后续出现错误，即使按 `--scope short`
解析也会判失败。保留全部已采集日志，不能截去后续故障而仅提交成功前缀。

两种背压仅支持长范围，保持 600/3600 秒真实通信与额外 10 秒观察收尾。
旧包继续使用自己的分析器和完整观察规则，不能仅添加命令参数便取得短范围验收。

建议里程碑矩阵为十六种场景各一轮：`m55-ipc-stall-recovery`、
`m55-recovery-ready-failure`、`ipc-sequential` 保留长范围，两种背压保留原合同，
其余十一项采用短范围。IPC/QUIESCE 的额外冷启动重复轮次可采用短范围，报告明确登记范围与次数。
修改时钟、计时器、复位或 IRQ，或出现未解释异常时，应增加受影响路径的长测。
60 秒观察不能等同于 600 秒的可靠性覆盖。

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

## 资源快照检查

`layout.json` 声明 `resource_service` 的镜像，除所选 IPC/生命周期证据外，还必须
包含资源快照记录。随包分析器校验早期阶段快照、M55 RELEASE 后的硬件快照；
生命周期场景还须包含保持复位时的快照，并核对 RAM 映射保持不变。
早期记录打印的是内核初始化前采集的数据，日志时间戳表示打印时刻。
缺少记录时所选验收范围为未完成，记录损坏或读回失败则判失败。
短观察窗口仍从全部功能步骤完成后起算。

离线打包检查只读描述符、客户端初始化及校验调用、完整常驻调用路径和服务栈预算。
这些检查不能替代物理冷启动测试，也不证明新板的引脚映射或电平适配。
