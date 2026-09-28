# Bestechnic HAL 模块

[English](hal.md)

`hal_bestechnic` 为 BES2700YP 的 Zephyr 集成提供预编译 HAL 静态库、接口头文件和链接脚本。`bootstrap` 链接这些库完成早期硬件初始化，并保留供 BTH 后续调用的硬件服务入口。

BTH 和 M55 的 Zephyr 镜像不直接链接 HAL 静态库；完整镜像中的启动与调用关系见[架构说明](architecture.zh-CN.md#hal-与硬件服务边界)。

## 运行期资源接口设计

本节定义资源服务的实现边界，不表示新增 API 或驱动已经可用。HAL 公共头文件仍为
bootstrap 接口。首个运行期使用者选择 BTH UART0；GPIO 须先明确实例和真实板级连接。
M55 不因此获得直接调用 BTH 静态库或配置共享 CMU/PSC/PMU/IOMUX 的权限。

### 最小操作与 HAL 缺口

下表操作名表示职责，尚未分配 ABI 编号或导出 C 符号。采用经审查实例的项目资源 ID，
不公开厂商枚举值、任意寄存器地址或无限制的位掩码。

| 操作 | 必须满足的行为 | 实现前提 |
|---|---|---|
| 能力查询与快照 | 不改硬件，报告已实现操作以及有效的时钟/门控/复位/引脚字段 | 常驻服务发现与字段有效性声明；现有时钟检查及快照只覆盖部分状态 |
| UART 输入频率查询 | 读取并解析实际时钟源/分频，核对期望频率 | 带寄存器读回的 HAL 小接口；常数不能证明当前硬件频率 |
| 外设门控开关 | 只操作已审查的末级门控并检查结果 | 受限小接口、所有权检查和有界访问；UART0 承担日志时保持常开 |
| 外设复位置位/释放/状态查询 | 用户停止后只操作拥有的实例 | 受限小接口及读回；活跃日志 UART、M55 CPU 和共享域不属于通用复位目标 |
| 引脚状态查询/应用 | 检查整个引脚组、所有者和依赖，读回 mux/pull | 实际读回和有界硬件锁；保留无关字段并考虑芯片修订差异 |
| GPIO 数据与 IRQ | 经 Zephyr 驱动支持一个已确认实例 | 寄存器语义、pad 映射、clock/reset 和中断路由评审；只有厂商头文件不够 |

库中已有 CMU 门控/复位原语，但它们不是公开支持的运行期资源 ABI。当前引脚功能读回
为占位实现；UART 电压设置未实现切换，通用电压接口成功也不能证明数字 pad 的实际电平。
IOMUX 锁中存在屏蔽本核中断后无界等待硬件锁的路径，必须先提供经过审查的实现，不能只
透传已有返回值。虽然厂商声明存在，交付库中没有 GPIO 方向及 IRQ 配置的实现。

首批资源 API 不提供电压切换、共享根时钟改频、DVFS、域掉电、M55 复位、RAM 重映射，
也不释放 bootstrap timer/mailbox 保留资源。合法但不支持的操作明确返回错误，不能用
成功的空操作满足 Zephyr 接口。

### 调用上下文与失败契约

资源服务发现必须早于 UART 设备初始化和 M55 PREPARE。调度器启动前采用单一所有者
初始化路径，不使用内核 mutex。启动后，资源状态修改与 M55 生命周期硬件操作共享
一个 BTH 仲裁机制；修改重叠寄存器前获取，生命周期等待阶段释放，不持锁等待 IPC、
UART 流量、回调或日志锁。诊断在释放资源锁后输出；短字段更新须恢复原中断状态，硬件
后端不睡眠、不分配内存，也不调用 Zephyr 回调。

逐项遵守锁定 Zephyr 的 API 上下文契约。尤其 `clock_control_off()` 要求非阻塞且可在
任意上下文调用，其支持路径须采用有界 try-acquire 和短硬件操作，竞争时立即失败。
不能实现为可睡眠 mutex，也不能在门控尚未关闭时以异步请求返回成功；未证明可行前
保持该操作不支持。可睡眠配置另走有界线程路径。引脚重配与多步复位不在 ISR 执行，
UART/GPIO 数据收发和 IRQ 处理保留在 Zephyr 驱动中。

Zephyr 边界统一以下结果：

| 返回值 | 含义 |
|---|---|
| `0` | 请求后置条件已确认；查询通过有效位声明哪些字段可信 |
| `-EINVAL` | 请求格式、资源 ID 或引脚组非法；不写硬件 |
| `-ENOTSUP` | 合法请求不属于已实现能力；不写硬件 |
| `-EPERM` | 保留资源或所有者错误；不写硬件 |
| `-EBUSY` | 仲裁不可用或其他使用者仍活跃；不写硬件 |
| `-EWOULDBLOCK` | 当前上下文不满足该操作要求 |
| `-ETIMEDOUT` / `-EIO` | 有界等待超时 / 后置条件失败；保留诊断及已完成步骤的状态 |

上述是小接口/适配层结果，厂商正数错误码须转换。未实现的 Zephyr 可选回调可按原生
API 返回 `-ENOSYS`。写入前预检完整请求；部分失败时仅恢复已证明可安全恢复的字段，
否则标记该资源故障并拒绝继续修改，不通过复位共享域修复局部错误。轮询同时使用经审查
时基和次数上限，避免计时器停走后形成无限等待。

### UART 接管与实现顺序

UART0 初始由 bootstrap 占用，设计状态为 bootstrap 所有 → 接管中 → Zephyr 所有，
硬件状态不确定时进入故障态。接管先只读检查继承的频率、引脚和门控/复位状态，停止普通
输出者、有界排空 TX、屏蔽并清理旧 IRQ，再初始化驱动并移交所有权；日志时钟保持常开。
未改硬件前的失败保留 bootstrap 所有权；重配置后的失败须经恢复读回确认或故障隔离，
不能无条件回退并继续输出。

所有普通输出路径，包括[bootstrap 契约](../platforms/bes2700yp/boot/bootstrap/bth_contract.h)
中的辅助函数，都须遵守新所有者，不能仅启用 Console 而保留旁路 UART 写入。
早期日志由 bootstrap 输出。fatal 日志采用独立、有界的紧急接管，屏蔽 UART 中断，
不能等待被中断输出者持有的锁；串口不可用时保留内存诊断。内部回环也须排除普通输出者，
恢复外部模式后再打印保存的结果，内部回环不能证明连接器接线或 I/O 电平。

实现按可评审步骤推进：服务发现与只读快照、有界 HAL 小接口、Zephyr 资源适配及精确
静态授权、UART 接管、GPIO 输入输出/上下拉/中断。每项授权均配合法及冲突测试。
GPIO 复位/门控须考虑同 bank 其他用户。引脚先实现 default 状态，sleep 状态及系统 PM
另行定义契约。[架构说明](architecture.zh-CN.md#资源服务扩展设计)规定服务位置与 ABI
评审要求，[测试说明](testing.zh-CN.md)规定证据保存方式。

## 版本如何匹配

集成仓通过以下文件确定并校验工作区中 `modules/hal/bestechnic/` 的内容：

| 文件 | 集成作用 |
|---|---|
| [west.yml](../west.yml) | 指定 HAL 仓库、检出路径和固定 Git 提交 |
| [module-lock.json](../module-lock.json) | 记录与 `west.yml` 相同的依赖提交，供一致性检查 |
| [hal-release.sha256](../hal-release.sha256) | 固定 HAL `manifest.json` 的 SHA256 |
| HAL 模块 `zephyr/module.yml` | 指定三个静态库的下载地址和 SHA256，与 HAL manifest 一致 |
| HAL 模块 `manifest.json` | 记录芯片、profile、ABI、编译器，以及库、头文件和链接脚本的哈希 |

[仓库检查](getting-started.zh-CN.md#检查依赖)核对版本记录、HAL manifest 和文件哈希，预期为 `status: pass`、`issues: []`。构建还会核对实际检出的 HAL 提交，以及芯片、profile、ABI 和编译器条件。HAL 提交变化会改变构建来源；新镜像需重新构建，并按改动影响验证。

## 检查失败时如何定位

| 报错或现象 | 处理方向 |
|---|---|
| `module-lock.json differs from west.yml` | 核对集成仓的 `west.yml` 与锁定文件是否来自同一提交 |
| `Module revision mismatch: hal_bestechnic` | 保存 HAL 本地改动后，从工作区按 `west.yml` 同步模块 |
| `HAL manifest.json SHA256 differs from hal-release.sha256` | 同步集成仓固定的 HAL 提交，核对集成仓文件版本 |
| 缺少静态库或库文件哈希不匹配 | 在工作区执行 `west blobs fetch hal_bestechnic`，重新获取固定版本的库 |
| `HAL blob metadata differs from manifest.json` 或下载地址不可用 | 核对模块版本及发布状态；元数据不一致时联系维护者，不修改哈希绕过检查 |
| 头文件、链接脚本等 Git 文件缺失或哈希不匹配 | 恢复集成仓固定的 HAL 提交 |
| `Unsupported HAL chip/profile/ABI` | 核对 HAL manifest 与当前集成配置的芯片、profile 和 ABI |
| `compiler differs from the audited HAL producer toolchain` | 按[工具链安装](getting-started.zh-CN.md#工具链安装)选用 manifest 要求的版本 |

首次同步和构建命令见[环境准备与构建](getting-started.zh-CN.md)。模块文件组成及适用条件以当前检出的 `modules/hal/bestechnic/README.md` 和 `manifest.json` 为准；许可与分发状态见同目录的 `THIRD_PARTY_NOTICES.md` 和 `distribution.json`。
