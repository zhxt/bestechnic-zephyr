[English](m55-restart.md)

# M55 保持 RAM 的正常重启验证

`m55-restart` 使用两核相同的固定 Zephyr 版本、24 MHz 及现有 HAL 库。初始启动加 10 次 M55 CPU
重启共 11 个 session，每会话双向各 1000 条消息，覆盖 0..96 字节。BTH 持续运行。
本场景不关闭 RAM 或电源域，不提供异常强制恢复或未知业务的自动重放。

## 构建和验收

沿用[构建说明](getting-started.md)，设置 `BES_VALIDATION_PROFILE=m55-restart`，使用独立构建目录。
最终镜像仍为 `zephyr.bin`，同包发布 `layout.json`、源码、审计及分析器。

```sh
python release/analyze_dual_restart.py current_boot.cap \
  --manifest release/layout.json --output analysis.json
```

应有 11 个 READY、22 条 endpoint、11 条 peer 健康摘要、11 次复位硬件快照及 session 结果，
以及 22 条 reset 采样记录（每会话 RELEASE/STOP 各一条）。
每个方向 sent=acked=对端 handled=1000，错误、意外拒绝、伪中断为零；每轮停止确认
peer_idle/reset_held/channel_clean，全程有 601 条 BTH 心跳。分析器返回 0/1/2 分别表示
通过/失败/不完整。测试必须针对相同候选身份，不沿用先前镜像的实板结论。

BTH 观察时长 600 秒。11 会话可能提前完成，随后 M55 保持 CPU 复位；不是 600 秒双核流量。
首轮关注第二个 session 是否能启动，完整通过后再做两轮断电重复验证。
修改公共 worker/mailbox/启动服务后还应回归 `ipc-backpressure`、`ipc-fault-injection` 和 `ipc-backpressure-1h`。

## 所有权及失败边界

BTH 管理器位于 `platforms/bes2700yp/lifecycle`，负责停止协作、装载、等待和会话。
bootstrap 仅通过既有公开 HAL 操作硬件；CPU 复位释放位的解释局限于该桥接层。
每次重启都重新校验实际装载内容，只有新会话 READY 后 BTH worker 才启动业务。

正常停止依次关闭业务、排空、等待本地 worker 停止、等待 M55 最后共享写入者确认、
断言并读回复位、清理 mailbox 通道 1。通道 0 保留。普通 RX disable 仍保留待处理通知；
reset 是单独操作，只能由持有本地访问者和对端 CPU 状态的管理器调用。

复位确认使用 BTH 6 MHz timer，预算 10 ms，最多轮询 1024 次，避免计时器停止导致无限等待。
复位读回失败进入 FAULT，禁止 REPARK；通道清理失败保持禁发并拒绝 resume。
READY/消息/QUIESCE 预算分别为 5/30/5 秒。错误立即记录并终止测试。

`zephyr_lifecycle` 正常重启协议 version=4、共享 ABI 为 `0x000a0004`。复位等待和独立采样函数均放在 bootstrap
SRAM，采样禁止内联，连续两次读 timer 的短临界区保存/恢复 PRIMASK。保留原先
`a>=b && a-b<=20` 判据，每次采样最多尝试 32 次；只有这两次读取屏蔽普通中断。
10 ms 从首次有效采样计至确认 reset 的采样，包含 HAL stop 操作；首次采样自身由
32 次重试约束，不能把此预算当成包括所有调度干扰的整个服务硬实时承诺。
采样失败仍断言 CPU reset 并进入 FAULT，不写全局 logger 的 error=91，也不清已有错误。

复位诊断独占 `0x2055c1a0..0x2055c1f0`，80 B，位于 logger 与 profile 之间的保留区。
每次调用先清空，只有实际进入复位等待才写 version=1；因此早于等待的服务拒绝不会
重复输出上次的有效诊断。reset 日志包含调用 op（RELEASE=3、STOP=4）、底层 service_rc、
reason、轮询/采样/尝试次数、末次 a/b、最大差值、elapsed tick、reset 前后值、timer control、
全局 diag_error、采样函数地址及进入等待时的 PRIMASK。成功分析器逐条验证这些字段，
并核对 sampler 地址与本包 ELF。底层负数返回值以 uint32 十进制打印。

| reason | service_rc | 含义 |
|---:|---:|---|
| 0 | 0 | reset 读回成功，采样与预算正常 |
| 1 | -7 | 32 次采样尝试耗尽 |
| 2 | -8 | 有效计时达到 10 ms |
| 3 | -9 | 1024 次轮询后仍未确认 reset |
| 4 | -10 | 已有全局计时错误 91 |
| 5 | -11 | timer 未处于使能的 32 bit 模式 |

最终 ELF 审计要求整个等待及采样函数落在文件支持的 SRAM 可执行段，采样不得调用
外部函数，并验证中断保护与真实调用关系。主机测试执行实际 C 采样及服务代码，覆盖
差值阈值、回绕、最后一次成功、重试耗尽、中断状态恢复和失败时保持对端复位。
主机模型与 ELF 审计不能证明真实总线时序；冷启动须观察首次 RELEASE、M55 READY、
session 2，再完成 11 会话和 600 秒 BTH 观察。

消息和重启场景共用 `platforms/bes2700yp/boot/service_contract.c` 校验服务入口。
Flash 代码执行窗口为 `0x14000000..0x14800000`，与 `0x34000000` 下载/装载视图不同；
同时允许既有 bootstrap SRAM 执行窗口，并检查 Thumb 位、ABI 和 TCM/mailbox 契约。
最终打包使用同一段 C 校验代码检查实际 ELF 中的服务地址、可执行段及应用调用关系。

入口失败会在 `begin rc=1` 后输出 `precheck`，包含 dispatch、service_layout、
service_errors、state_errors 及 CPU 状态。service_errors 位 0..6 分别表示 magic、
layout、Thumb、执行窗口、ITCM、DTCM、mailbox 不符；state_errors 位 0..7 分别表示
CPUID、VTOR、CONTROL、IPSR、PRIMASK、BASEPRI、频率、guard 不符。
该记录表示失败，不改变正常会话的日志与共享 ABI。

`platforms/bes2700yp/resources.json` 和公开头定义契约。控制区为
`0x2015e280..0x2015e300`，128 B，BTH/M55 各写 64 B，带 session 和 guard。
两核 DTS 显式保留；heartbeat 链接区限制为 128 B，ELF 的文件段及零初始化范围均经过审计。
CPU 复位下的 SRAM 可访问性、寄存器同步和真实 IRQ 时序仍以实板测试为准。

## 保持 CPU reset 时重新 PARK

后续 10 会话在 step=1 与 step=2 之间各输出一条 repark 记录。CPU reset 期间不直接
读写 M55 的 DTCM 窗口；该条件也适用于故障快照，复位态的 vector_sp/vector_pc 写 0，
不把它们解释为实际向量内容。初始 PARK 和应用 RELEASE 保持原有顺序。

bootstrap 调用 HAL 公共 `bes2700yp_m55_repark_prepare()`，只临时切换包含 PARK 向量的
物理 bank 9（SYS_RAM_SEL0 mask `0x38000000`）到 AXI RAM。三个字经官方交织地址映射
写到 `0x20320000/0x20320004/0x20330000`，期望内容分别为
`0x2015ffe0/0x200c0009/0xe7fdbf30`。读回成功后恢复原 selector，完整核对 SEL0/SEL1
并确认 CPU 仍保持 reset，服务才释放 M55。其余 bank、时钟、电源域均不由该 API 修改。

前提是两核访问者已经静止，BTH 独占映射管理，cache 关闭，配置为当前固定内存布局。
每次映射等待最多 32 次读回。切换或写入失败仍尝试恢复原 selector；任何错误都进入
phase=5，禁止 start/REPARK。恢复失败必须保留故障，不把失败当成可以继续运行。

专用 repark 诊断在 `0x2055c800..0x2055c864`，100 B，与 boot profile 和 reset 诊断分离。
日志保存 version/op、原始 service_rc、phase_before/after，以及 HAL 的 reason、reset 前后、
SEL0/SEL1 原值/AXI 值/恢复值、三个物理地址、预期值、实际读回、restore_ok 和 write_mask。
`reset_after` 采样发生在 HAL preparation 返回前、CPU 释放前；成功时应仍为 held。

| reason | service_rc | 含义 |
|---:|---:|---|
| 0 | 0 | 写入、读回、映射恢复和 reset 检查均通过 |
| 1 | -21 | 进入时 CPU 未保持复位 |
| 2 | -22 | bank 9 所有权与预期 DTCM 不符 |
| 3 | -23 | AXI 映射读回失败 |
| 4 | -24 | PARK 三字读回不符 |
| 5 | -25 | 原映射恢复读回失败 |
| 6 | -26 | 操作期间 CPU reset 状态丢失 |

解析器要求 10 条成功 repark 记录，映射与上一会话的 hardware 快照一致，只有目标
selector 在 AXI 阶段改变，三个字及恢复结果逐项正确。缺失记录和旧 ABI 不能通过。
集成主机模型在 CPU reset 时用内存保护禁止 DTCM 访问；producer 单独测试实际 HAL
代码的物理地址、其他内容保持、映射失败恢复及 PRIMASK 保存。两类模型都不能替代实板。

## 故障隔离场景

`m55-ready-timeout` 和 `m55-heartbeat-stop` 验证 BTH 健康时对 M55 故障的最终隔离，
沿用正常重启的保留 RAM 服务及固定时钟/cache 配置。sysbuild 命令使用
`-DBES_VALIDATION_PROFILE=<场景名>` 选择；默认场景不注入 CPU 停止。

前者让 M55 在发布 READY 前关闭中断并停止；后者在发布十次心跳后关闭中断并停止，
不依赖业务消息是否已完成。BTH 使用本地时间，在等待 READY 达 5000 ms 或心跳
连续 1000 ms 未推进时报告故障。快照读取有界，不可读的 seqlock 不刷新期限，
迟到的心跳不能解除已锁存故障。可复用策略位于 `platforms/bes2700yp/lifecycle/health.c`。

隔离先禁止本地 mailbox 新发送并屏蔽收发中断，保留对端通知状态，再终止本地 worker。
这里限定当前单处理器 Zephyr 镜像：worker 不持有 mutex 或动态分配资源，回调只投递
信号量。然后断言并读回确认 M55 CPU reset，最后清理硬件通道 1；任何一步失败都禁止
后续步骤。无需对端 QUIESCE 确认，不在复位态读取 DTCM，不执行 REPARK、重新装载、
业务重放或自动重试。CPU reset 不能证明其他总线主设备已停止，本场景不启用 DMA。

隔离后 BTH 继续观察，累计从监测开始的 600 秒、601 条 sample；结束时再次确认
M55 保持复位，通道 1 两端的原始通知/完成标志已清除。预期 reason 为 1（READY 超时）
或 2（心跳停止）；意外故障或隔离失败即使 BTH 仍存活也不能通过验收。

保留完整的匹配包，使用包内分析器：

```sh
python release/analyze_dual_isolation.py current_boot.cap \
  --manifest release/layout.json --output analysis.json
```

分析器核对注入标记、检测时间、RELEASE/STOP 复位诊断、本地静止/复位保持/通道清理、
完整 BTH 观察及 `isolation_result pass=1`，并要求 releases=1、recoveries=0。
退出码 0/1/2 表示通过/失败/不完整，不能只看最后一行判定通过。里程碑验收时每场景
保存三次独立物理断电上电记录，先检查首轮完整结果，再做重复测试。串口日志不能证明
物理断电，操作方式需单独记录。主机测试覆盖期限、隔离各步失败、真实 worker 的终止门控、
mailbox 寄存器模型及解析器负例，不能代替真实复位和总线时序验证。

公共 worker、mailbox 或 bootstrap 变化仍需回归正常重启及四种消息场景。
下述恢复场景在隔离边界之后增加一次受控重载。

## 一次受控故障恢复

`m55-ready-recovery` 和 `m55-heartbeat-recovery` 仅在 session 1 注入对应故障。
隔离成功后，BTH 每次启动最多执行一次恢复尝试。`health.c` 中的固定预算策略拒绝
不完整的隔离前提，并在调用任何恢复操作前消耗本次尝试额度。

管理器先执行 REPARK 并检查 RAM selector，再重建 BTH worker。确认旧线程已终止后，
清理本地启动、停止和接收信号量、报告及计数，以原有静态线程对象和栈创建休眠线程。
只有 PARK 使装载窗口可访问后才重新初始化共享环及 M55 状态；装载内容经过 CRC
校验后才释放 CPU。session 2 的 READY 校验通过后，新 BTH worker 才开始通信。
旧请求和通知被丢弃，不自动重放业务；当前验证应用没有外部调用者或请求取消接口。

session 2 必须双向各完成 1000 条消息、核对 M55 健康状态，再完成正常协作的
QUIESCE/复位/通道清理。随后 M55 保持复位，BTH 从监测开始累计观察 600 秒。
这验证恢复通信及正常收尾，不表示 600 秒双核流量。原有两个隔离场景继续保持最终隔离行为。

REPARK、worker 重建、装载、释放、READY 或通信任一步失败，都禁止后续恢复步骤。
管理器再次尝试隔离，记录失败步骤和隔离结果，BTH 继续监测，不进行第二次重载。
复位确认失败不能记作保持复位成功。更多故障与恢复失败场景见下节。
多次恢复以及 BTH/整机复位恢复留在后续批次。

按对应场景构建，使用完整匹配包的分析器：

```sh
python release/analyze_dual_recovery.py current_boot.cap \
  --manifest release/layout.json --output analysis.json
```

分析器要求原故障及隔离证据、唯一的
`recovery_begin old_session=1 new_session=2 limit=1`、REPARK 读回、`worker_rebuilt`、
session 2 的 READY、两端完整消息计数和正常停止结果。最终复位/通道检查及 601 条
BTH sample 后，才允许 `recovery_result pass=1 session=2 releases=2 attempts=1 recoveries=1`
通过；reason 必须匹配，rc 必须为零。缺失步骤、旧会话或未完成观察均不能通过。
隔离及正常重启分析器会拒绝恢复场景。

先检查每个场景一轮完整冷启动。里程碑候选冻结后，再为每个恢复场景收集三轮独立
物理断电启动和受影响的公共路径回归。主机模型覆盖真实 worker 通信中途终止、带残留
信号的重建、新会话隔离、单次预算及失败门控、解析器负例；实际寄存器时序和恢复能力
仍须使用关联镜像 SHA256 的实板证据确认。

## 扩展故障及恢复失败场景

以下均为可选验证应用，沿用上述 sysbuild 场景选择及同包 `analyze_dual_recovery.py`
命令，不改变默认场景，也不自动为业务应用启用恢复。

| 场景 | 注入行为 | 必须达到的结果 |
|---|---|---|
| `m55-ipc-stall-recovery` | M55 worker 消费至少 32 条消息后休眠，心跳继续 | 有未完成请求且 1000 ms 无消息进度；reason=4，恢复 session 2 |
| `m55-quiesce-recovery` | session 1 完成通信，但拒绝 idle 确认 | 心跳继续，QUIESCE 等待 5000 ms 超时；reason=5，随后恢复 |
| `m55-fatal-recovery` | session 1 在十次心跳后调用 `k_panic()` | 读取有效 fatal 发布，reason=6，随后恢复 |
| `m55-fatal-unreadable-recovery` | 同样触发 panic，fatal handler 将状态序号留在奇数 | 不可读状态不刷新心跳期限；reason=2 超时，随后恢复 |
| `m55-repark-failure` | 心跳停止隔离后，在硬件操作前拒绝 REPARK | 再次确认复位，拒绝第二次尝试；一次 RELEASE、零次恢复 |
| `m55-load-failure` | REPARK、worker 重建后，在写 RAM 前拒绝装载 | 再次隔离、拒绝第二次尝试；一次 RELEASE、零次恢复 |
| `m55-recovery-ready-failure` | 新 M55 在 READY 前停止 | 新会话 READY 超时，再次隔离并拒绝重试；两次 RELEASE、零次恢复 |

IPC watchdog 仅在确有未完成请求时监测 ACK 和消费计数；空闲不启动超时。
worker 通过 BTH 本地带锁报告发布实时进度，管理器不直接无锁复制线程可变状态。
迟到的进度不能解除已到期的期限。注入选项和标记只用于验收，不参与健康策略判定。
M55 所有的控制字 `unused[0]` 记录验证用的 panic 前标记；控制区尺寸和共享 ABI 数值不变。
fatal 发布缺失时只能确认心跳超时，不能声称已解析具体异常原因。

REPARK/装载失败场景注入的是软件操作错误，不会破坏硬件 selector，也不能据此声明
真实 RAM/读回故障已经完成实板验收。复位服务错误及映射失败门控仍由主机模型和离线
检查覆盖；真实硬件失败需另有证据。意外隔离失败仍判为失败，BTH 存活不能代替成功隔离。
失败场景要求 `recovery_failed`、`retry_blocked`、最终 held/通道检查，以及
`recovery_failure_result pass=1 attempts=1 recoveries=0`。这里的通过表示预期失败已被
正确隔离，不表示 M55 恢复成功；不能使用成功恢复的结果行替代。
两类结果都仍要求 601 条样本及完整 600 秒 BTH 观察，本批不启用缩短验收范围。

生命周期日志采用 `BTH/LIFECYCLE/MAIN` 和 `zephyr_lifecycle`，包内 `lifecycle_log`
声明文本格式 version=2；正常重启协议 version=4 及共享内存 ABI 保持不变。
历史日志保留原包分析器，新分析器拒绝混用旧、新命名空间。
