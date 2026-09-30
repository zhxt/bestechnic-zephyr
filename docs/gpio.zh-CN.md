# 受限 GPIO 验证

[English](gpio.md)

`gpio-input` 和 `gpio-led` 两个 sysbuild 场景在正常双核 IPC 运行时验证一条由 BTH 管理的 GPIO 路径，
通过 bootstrap 服务调用自有 HAL 接口。它们不注册 Zephyr GPIO/pinctrl 控制器，
不配置 GPIO 中断，也不把共享硬件的管理权转移给 M55。

| 场景 | 输入 | 输出 | 默认状态 |
|---|---|---|---|
| `gpio-input` | P2_0、P2_1，内部上拉，低有效 | 无；保持 P1_4/P1_5 原状 | 可选，普通场景不启用 |
| `gpio-led` | 相同两个输入 | P1_4，低有效；先预置高再使能输出 | 可选，需确认电气条件 |

上述映射对应 BES27001.2 参考原理图中的 S3/S4 和 D2。P1_5 上的 D3 保持原状作为
对照。外观相似不能证明另一块板的接线和电压一致，应核对实板的按键和 LED 连线。
P2_2/P2_3 继续保留给 UART；电源键和复位键不是测试输入。

使用输出场景前，测量模块 VIO 与 D2/D3 限流电阻供电端电压，依据实际模块和板卡
资料核对输入电压上限与 LED 电流。服务不修改电压选择或驱动强度。寄存器读回不能
证明电气兼容性或 LED 肉眼可见的亮灭。输入场景不修改 LED 的复用、上下拉、方向
和输出锁存，原本常亮的 LED 可以继续常亮。

## 构建与操作

使用[常规 sysbuild 命令](getting-started.zh-CN.md)，增加
`-DBES_VALIDATION_PROFILE=gpio-input` 或 `-DBES_VALIDATION_PROFILE=gpio-led`，
每个场景使用独立构建目录。刷入完整 `zephyr.bin`，按文档波特率记录完整启动和应用日志。

1. 先使用 `gpio-input`，物理断电上电，看到 `zephyr_gpio waiting` 后再操作按键。
2. 两个按键分别至少完成 10 次按下、松开，顺序不限。每次按住和松开建议各约半秒。
   应用每 10 ms 轮询，稳定 50 ms 才计入状态变化。上电时已按住的按键不算一次按下，
   需要先松开。人工操作期限为五分钟。
3. `gpio-led` 中重复上述按键操作。P1_4 初始为高（灯灭），每秒低/高交替，完成
   10 次完整闪烁后保持高。观察 D2，确认 D3 保持原状。应用还会在输出切换后至少
   等待 10 ms，再检查焊盘输入电平。
4. 两键最后均需松开。GPIO 与顺序 IPC 检查全部完成后，日志输出
   `zephyr_gpio result ... pass=1` 和 `zephyr_observe functional`，然后等待
   `zephyr_observe result version=1 scope=1 pass=1`，完成随后的 60 秒健康观察。
   同一镜像可以继续运行到长观察检查点；短窗口通过不等于长时测试通过。

使用与镜像对应的源码脚本和 layout.json 分析：

```sh
.venv/bin/python bestechnic-zephyr/scripts/analyze_dual_message.py capture.cap \
  --manifest build/gpio-input/release/layout.json --scope short \
  --output build/gpio-input-analysis.json
```

分析输出场景时替换构建目录。解析器同时核对启动身份、IPC、GPIO 记录和观察窗口；
只有 GPIO result 不构成完整验收。物理断电、电压测量和 LED 目视结果应关联镜像
SHA256 单独记录，串口不能证明这些事实。人工操作超时表示本轮操作未完成，不能
单凭这一点判定 GPIO 硬件故障。

## 接口与所有权

发现操作 9、参数 4 返回 32 字节描述符，ABI 为 4，能力值 40 表示输入/读回/采样，
56 表示同时提供输出。原有服务 ABI 含义不变。
[接口契约](../include/bestechnic/bes2700yp/bes2700yp_gpio.h)使用 96 字节请求，其中
包含 64 字节快照：阶段、锁存故障、候选引脚输入/方向/锁存、完整 P1/P2 复用与
上下拉寄存器、AON 门控/复位状态及 GPIO IRQ/控制状态。

| 操作 | 允许参数 | 线协议错误返回 |
|---|---|---|
| 1 读回 | pin=0，value=0 | -1 参数；-2 不支持；-3 上下文；-4 忙；-5 不可用；-6 故障 |
| 2 输入 | pin=16 或 17，value=0 | 同上 |
| 3 输出 | pin=12，value=0 或 1；仅输出场景 | 同上 |
| 4 写值 | 已配置为输出的 pin=12，value=0 或 1 | 同上 |
| 5 采样 | pin=0，value=0；仅头部、pins 和 inputs，其余字段为零 | 同上 |

调用方须为中断已使能的特权 BTH 线程。所有调用均取得生命周期仲裁保护，在被抢占时
继续持有所有权；只有 RAM 仲裁状态更新短暂屏蔽中断，硬件访问期间保持中断开启。
写操作复核运行/隔离阶段；完整读回和写操作仅尝试一次 AON MEMSC0，忙则立即返回。
采样只检查 bank 可用性并读引脚输入，不获取 MEMSC0、不读配置寄存器。ISR 不得获取
MEMSC0 或调用厂商 IOMUX 配置入口。M55、ISR、非特权和已屏蔽中断的调用均不支持。
能力位 32 标识采样契约；客户端拒绝缺少该能力位的旧描述符。

GPIO bank 须已开启时钟并解除复位。服务不复位整个 bank、不修改门控、不使能中断，
也不修改引脚电压。输入配置只改目标引脚的复用/上下拉位；输出配置先禁止该引脚输出、
预置锁存、设置复用/上下拉，最后使能输出。目标引脚已有 IRQ 或硬件控制占用时拒绝操作。
写后读回失败会将该引脚置为输入并锁存服务故障；重启前拒绝后续写入，仍允许读回。
这是故障收敛，不是事务式恢复此前全部引脚配置。

应用每 10 ms 采样输入，每秒及配置/输出操作后将完整快照与初始状态比较。
D2 首次切换在一秒后到期；两键各完成十次完整按下/松开前持续等待，交互期限为五分钟。
原有内核/独立计时器健康阈值保持不变。

第 1 次及每第 10 次健康采样、健康检查失败时，输出版本 2 的 `zephyr_gpio timing`：
采样/完整读回/写操作次数、独立 fast timer 记录的最大调用耗时、入口/出口屏蔽中断
异常及 SysTick LOAD/VAL/pending。调用耗时包含抢占时间，不代表关中断时间。
诊断不读取 SysTick CTRL/COUNTFLAG，避免干扰内核计时。解析器要求这些记录，拒绝
屏蔽中断异常、缺失记录和过于频繁的完整快照读取。

ELF 审计核对描述符/能力一致性、有限执行的
纯整数 HAL 调用及栈预算。主机测试执行实际服务、客户端、交互应用、去抖和 HAL 掩码操作，
覆盖拒绝路径及日志变异测试。这些检查补充实板验证，不证明 GPIO 中断路由或完整
Zephyr GPIO 驱动已经实现。

## 标准 Zephyr GPIO API

`gpio-api-input` 与 `gpio-api-led-restart` 场景启用
[BTH GPIO 驱动](../bsp/drivers/gpio/gpio_bes2700yp.c)及
[基于服务的控制器 binding](../bsp/dts/bindings/gpio/bestechnic,bes2700yp-gpio.yaml)。
现有 HAL 与 bootstrap 服务继续管理硬件。驱动提供引脚配置、端口原始输入、
掩码输出、置位、清零及翻转；Zephyr 处理低有效逻辑转换，raw 操作保留物理电平语义。

| 引脚 | 支持配置 | API 访问范围 |
|---|---|---|
| P2_0 / 16、P2_1 / 17 | `GPIO_INPUT | GPIO_PULL_UP` | 两个场景均提供；仅输入场景配置按键 |
| P1_4 / 12 | 推挽输出，可指定初始高/低 | 仅输出场景 |
| 其他引脚，包括 P1_5 及 UART 引脚 | 不开放 | DTS 保留，驱动拒绝访问 |

方向按引脚限定。不支持下拉、无偏置输入、开漏、断开模式及 M55 调用。这两个轮询场景不启用 IRQ。
设备初始化仅验证服务描述符，应用在 M55 启动后配置引脚；`device_is_ready()`
不表示当前生命周期阶段允许写操作。未支持 GPIO hog 及初始化期间自动配置的
LED/输入消费者。板级禁用的 `gpio-keys`、`gpio-leds` 节点仅提供 DT specifier。

调用要求特权 BTH 线程且 PRIMASK、BASEPRI 均为零。ISR 或屏蔽中断的上下文返回
`-EWOULDBLOCK`，不访问硬件。每设备非阻塞信号量串行化调用，包括翻转时的输出
锁存读写；争用也返回 `-EWOULDBLOCK`，应用可在线程中稍后重试。AON 访问不持有
屏蔽中断的自旋锁。不能混用直接服务写操作和驱动写操作；只读诊断快照可以保留。
应用应在同一上下文完成引脚配置，再并发执行数据操作。

非法引脚/掩码返回 `-EINVAL`；不支持的方向、标志和 IRQ 配置返回 `-ENOTSUP`。
尚未成功配置输出时，写入返回 `-EACCES`。服务错误向上传递，故障锁存后的读取返回
`-EIO`；端口读取失败不修改输出参数。GPIO 时钟和复位须已处于可用状态，驱动
不改门控、复位、电压或驱动强度，也不提供独立 pinctrl 控制器。

在常规 sysbuild 命令中使用 `-DBES_VALIDATION_PROFILE=<名称>`：

- `gpio-api-input`：看到 `zephyr_gpio waiting` 后操作两键，各完成十次按下/松开，
  等待功能完成后的 60 秒 short 结果。通过 `gpio_pin_configure_dt()` 配置，
  `gpio_port_get_raw()` 采样，每秒完整服务快照只用于诊断。用 `analyze_dual_message.py` 分析。
- `gpio-api-led-restart`：无需按键。通过 `gpio_pin_configure_dt()` 将 D2 初始化为熄灭，
  在 11 个 M55 会话中分别翻转为点亮、停止后设为熄灭。每次切换检查实际 pad 和
  配置，写入前先检查跨重启保持，避免新写操作掩盖状态丢失。D3、按键及 UART
  配置保持不变。22 次切换后 D2 保持熄灭，随后每秒继续检查。用
  `analyze_dual_restart.py` 分析；上板输出前完成前述电气核对。

两个分析器均要求匹配的 release/layout.json，支持 `--scope short`。输出场景在
完整生命周期和观察协议之外记录 `zephyr_gpio_api` 的 baseline/checkpoint/observe。
short 通过要求全部 11 个会话和功能后的 60 秒；观察窗口不替代功能步骤。
更长运行另行登记。物理断电、LED 目视及电压仍需外部记录。

## 按键边沿中断

`CONFIG_GPIO_BES2700YP_IRQ` 为 P2_0/P2_1 增加物理上升沿、下降沿和 Zephyr callback。
双边沿、电平触发返回 `-ENOTSUP`，不使用软件翻转极性模拟双边沿。唤醒、低功耗、任意
引脚及 M55 GPIO 所有权不在接口范围内。原轮询场景保持不启用 GPIO IRQ。

路径为 AON GPIO bank → PSC BTH GPIO 路由 → BTH NVIC IRQ 44，优先级 3。
发现操作 9、参数 5 返回独立 ABI 5 描述符，能力位 64，诊断请求 96 字节、状态 64 字节；
原 GPIO 服务不变。[IRQ 契约](../include/bestechnic/bes2700yp/bes2700yp_gpio_irq.h)
区分 READ、CLAIM、CONFIG、ACK。CONFIG 接受 pin 16/17，模式 0 禁用、1 下降沿、2 上升沿；
ACK 返回所拥有的 pending 掩码。线协议错误：-1 参数，-2 所有权冲突，-3 bank 不可用，
-4 状态/读回故障，-5 未取得所有权或阶段不可用，-6 上下文或并发入口。

驱动先将两键配置为上拉输入，再取得入口所有权。已有 BTH GPIO 路由、其他核路由目标
引脚、非 GPIO 的活动 AON 状态或不兼容的 mux/direction/pull 都会被拒绝。只增加 GPIO
唤醒汇聚门控，保留其他继承位。这是限定所有权的汇聚入口；扩展其他来源须另行设计共享分发。

线程 CONFIG 和完整 READ 使用 GPIO 设备信号量串行化，并只屏蔽 IRQ 44，其他 IRQ 保持
开启。服务拒绝 IRQ 44 仍使能、或 PRIMASK/BASEPRI 非零的线程调用。短全局临界区仅保护
RAM 记账，不覆盖硬件访问。重配前屏蔽并禁用目标位，只清除该位的使能前残留；禁用一个
按键保留另一按键路由。修改 GPIO 输入配置前须先禁用该引脚 IRQ。

ISR 读取路由状态，只确认自己拥有的位，再执行 Zephyr callback，不使用 MEMSC、不等待
信号量、不打印、不去抖。callback 可移除自身并通过独立标量路径禁用按键；ISR 内使能或
改变极性返回 `-EWOULDBLOCK`。普通 GPIO 读写仍只供线程使用。
`bes_gpio_irq_get_stats()` 返回原始事件、故障和以内核硬件周期计的最大 ISR 耗时；
`bes_gpio_irq_get_state()` 在线程中安全读取完整硬件快照。

未知 AON 状态保留 pending。服务失败、连续八次空入口或一个 100 ms 统计区间内超过
256 次入口，会锁存故障并禁用 NVIC IRQ 44。故障后需重启；不自动重试，也不据此声明
输入频率能力。

应用 callback 只写有界事件队列，溢出明确失败。线程以 10 ms 采样、50 ms 去抖；IRQ
使能阶段每个完整按下/松开周期必须有新中断证据。机械抖动可能产生更多原始 IRQ，不能
要求一次操作恰好一次 IRQ。明确禁用的阶段用轮询证明按键实际动作，并要求 callback 零增长。

| 场景 | 必需操作 | 分析器 |
|---|---|---|
| `gpio-irq-input` | 阶段 1/2：下降沿/上升沿，两键各十次；阶段 3：禁用 IRQ，两键各一次；阶段 4：恢复下降沿，两键各一次 | `analyze_dual_message.py` |
| `gpio-irq-restart` | 阶段 10：IPC/重启前两键各十次；阶段 11：11 会话/10 次重启后各十次 | `analyze_dual_restart.py` |
| `gpio-irq-recovery` | 阶段 10：IPC 停滞注入前两键各十次；阶段 11：一次恢复后各十次 | `analyze_dual_recovery.py` |

每次等待 `zephyr_gpio_irq prompt`，先松开两键，再按提示操作；每个电平至少保持 150 ms。
每阶段交互上限 180 秒。测试专用的 M55 worker 等待 BTH worker 首次发布，心跳监测持续；
交互后 IPC、READY、复位、进度和 QUIESCE 的超时不变。IRQ 配置和 callback 注册跨越重启、
恢复及观察阶段保留。

分析器使用匹配 release 的 `layout.json`。`--scope short` 检查完整功能结束后 60 秒；
`--scope long` 使用已有 600 秒健康观察契约。等待不能代替真实按键证据；必须有交互阶段、
边界配置保持和 IRQ 健康快照。这里只验收按键事件和控制；精确边沿计数及频率上限需要
干净的外部信号或固定方向回环。
