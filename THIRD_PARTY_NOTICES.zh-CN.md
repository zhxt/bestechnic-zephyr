# 来源与许可范围

[English](THIRD_PARTY_NOTICES.md)

本文说明本仓文件及固件主要依赖的来源、许可范围和查阅入口。具体使用与分发条件应结合所用版本的文件声明、随附许可材料及适用协议核对。

## 本仓文件

本仓包含 BES2700YP 的 Zephyr 适配代码、应用示例和构建工具。带有 `SPDX-License-Identifier: Apache-2.0` 标识的文件适用本仓 [LICENSE](LICENSE)，文件中已有的版权和来源声明应予保留。本仓许可证不改变外部依赖或厂商制品的许可条件。

本仓部分文档和配置文件尚未标注 SPDX 许可标识，其许可归属需结合具体文件的声明和来源核对，不据根目录的 `LICENSE` 将其统一归为 Apache-2.0。

## Zephyr 与 CMSIS 依赖

Zephyr、CMSIS 和 CMSIS_6 由 west 按 [west.yml](west.yml) 指定的提交取得；[module-lock.json](module-lock.json) 记录相同提交供一致性检查。下表路径相对于工作区根目录：

| 依赖 | 来源仓库 | 许可查阅位置 |
|---|---|---|
| Zephyr | [zephyrproject-rtos/zephyr](https://github.com/zephyrproject-rtos/zephyr) | `zephyr/LICENSE`、`zephyr/README.license` 及具体文件声明 |
| CMSIS | [zephyrproject-rtos/cmsis](https://github.com/zephyrproject-rtos/cmsis) | `modules/hal/cmsis/LICENSE.txt` 及具体文件声明 |
| CMSIS_6 | [zephyrproject-rtos/CMSIS_6](https://github.com/zephyrproject-rtos/CMSIS_6) | `modules/hal/cmsis_6/LICENSE` 及具体文件声明 |

依赖仓库可能包含适用不同许可证的组件。核对具体文件或固件所用组件时，应查阅锁定版本随附的声明。

## BES HAL 模块

本项目按 [west.yml](west.yml) 中的固定提交获取 `hal_bestechnic` 模块。该模块提供预编译静态库和厂商来源的链接脚本；本仓的 [LICENSE](LICENSE) 不为其中的厂商来源内容提供额外授权。

HAL 制品的来源、第三方声明及许可范围见工作区 `modules/hal/bestechnic/THIRD_PARTY_NOTICES.md`，公开分发状态见同目录的 `distribution.json`；具体使用与交付条件请核对模块声明及适用协议。
