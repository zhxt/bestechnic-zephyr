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

`zephyr_r1` 日志 version=4、共享 ABI 为 `0x000a0004`。复位等待和独立采样函数均放在 bootstrap
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
