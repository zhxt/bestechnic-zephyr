# Bestechnic HAL 模块

[English](hal.md)

`hal_bestechnic` 为 BES2700YP 的 Zephyr 集成提供预编译 HAL 静态库、接口头文件和链接脚本。`bootstrap` 链接这些库完成早期硬件初始化，并保留供 BTH 后续调用的硬件服务入口。

BTH 和 M55 的 Zephyr 镜像不直接链接 HAL 静态库；完整镜像中的启动与调用关系见[架构说明](architecture.zh-CN.md#hal-与硬件服务边界)。

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
