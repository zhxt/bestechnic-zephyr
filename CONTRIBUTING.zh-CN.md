# 贡献指南

[English](CONTRIBUTING.md)

## 开发准备

按[环境准备与构建](docs/getting-started.zh-CN.md)建立工作区，使用 [west.yml](west.yml) 指定的 Zephyr、CMSIS、CMSIS_6 和 HAL 模块提交及配套工具链。日常开发从持续演进的 `main` 创建短期 `feat/*` 或 `fix/*` 分支，分支与候选管理见[分支与发布](#分支与发布)。

首次贡献可按以下顺序进行：

1. 从 `main` 创建短期分支。
2. 阅读[架构说明](docs/architecture.zh-CN.md)，完成改动并更新受影响的文档。
3. 按[提交前验证](#提交前验证)选择检查，记录实际结果及未完成的验证。
4. 只暂存本次改动，使用 `git -C bestechnic-zephyr diff --cached` 检查将提交的内容。
5. 按[提交规范](#提交规范)创建提交，在 PR 中说明行为变化及验证结果。

英文版为默认文档；功能变更同步更新对应的英文和中文主题文档，README 保持简短。[测试说明](docs/testing.zh-CN.md)列出构建、主机回归与实板验收的具体步骤。

修改驱动、默认配置或支持范围时，同步更新[硬件说明中的支持范围](docs/hardware/bes2700yp.zh-CN.md#当前支持范围)及 [README 适配状态摘要](README.zh-CN.md#当前适配状态)，分别说明实现情况、默认是否启用和验证范围。发布记录中的实板结论必须关联具体镜像 SHA256 及对应报告。

## 修改范围与目录

各目录职责见[架构说明](docs/architecture.zh-CN.md#目录职责)。保持芯片支持范围明确，BTH/M55 不依赖对方应用的私有目录。新增或移入文件时先核对来源和许可；可加注释的自有源码和配置文件使用适用的 SPDX 标识，文档及无法加注释的元数据在[来源与许可范围](THIRD_PARTY_NOTICES.zh-CN.md)中明确适用范围。第三方文件保留原始来源、版权和许可，不自动改为本项目许可证。

新增文件后，确认其被 [scripts/project_files.json](scripts/project_files.json) 中对应的构建或归档规则覆盖。现有目录规则会自动收集匹配的源码；未覆盖的新目录、文件类型或文档，再调整清单。构建输入必须同时纳入源码归档，二进制测试数据需按清单登记并记录来源。

固件标识由 `build` 清单选出的文件及构建依赖共同决定。普通文档正文、测试和编辑器配置不在当前构建清单中，但清单文件本身参与摘要计算，修改清单可能影响固件标识。详细关系见[构建标识与来源记录](docs/architecture.zh-CN.md#构建标识与来源记录)。

格式以 [.editorconfig](.editorconfig) 和现有模块为准：使用 UTF-8、LF，Python 使用四空格缩进，C/汇编沿用所在模块风格。无关格式调整单独提交。构建产物写入工作区的 `build/` 或指定临时目录，实板记录保存在 `validation/` 等源码仓库之外的位置，本机排障日志和完整历史记录不纳入源码。

## 提交前验证

按改动实际影响选择验证范围：

| 改动类型 | 验证要求 |
|---|---|
| 文档 | 格式和仓库检查；逐一核对改动涉及的链接、标题锚点及示例命令参数 |
| 脚本或测试 | 仓库检查、相关主机回归；涉及构建流程时补充构建验证 |
| 构建、依赖或布局 | 仓库检查、主机回归、干净构建和离线审计；影响硬件行为时补充实板验收 |
| 启动、驱动或通信行为 | 仓库检查、相关主机回归、干净构建、离线审计及对应实板验收 |

从[已初始化的工作区根目录](docs/getting-started.zh-CN.md#初始化与依赖检查)执行基础检查：

```sh
git -C bestechnic-zephyr diff --check
.venv/bin/python bestechnic-zephyr/scripts/check_repo.py
```

已有暂存改动时也运行 `git -C bestechnic-zephyr diff --cached --check`。`git diff --check` 检查空白错误；`check_repo.py` 检查本地文档链接的目标文件是否存在，不检查标题锚点或示例命令参数，文档改动需另行核对这些内容。仓库检查应返回 `status: pass` 且 `issues` 为空。

需要主机回归时执行：

```sh
.venv/bin/python bestechnic-zephyr/scripts/test_host.py
```

干净构建、离线审计和实板验收按[测试说明](docs/testing.zh-CN.md)执行。提交或 PR 说明应列出实际执行的检查及结果；未执行的检查说明原因和剩余验证项，不将待测项目写为通过。

验证场景入口属于当前验证应用，未来业务应用无需沿用固定场景、时长和停止逻辑。修改场景选择或元数据契约时，应检查默认参数、非法参数拒绝、两核配置和发布包内分析器；改变运行行为时还需对应实板验收。

## 提交规范

提交信息参考 [Zephyr 提交指南](https://docs.zephyrproject.org/latest/contribute/guidelines.html#commit-message-guidelines)和[贡献者要求](https://docs.zephyrproject.org/latest/contribute/contributor_expectations.html)，本仓采用下列约定，构建与验证按本文及测试文档执行。

- 提交标题采用 `area: summary`，需要时细分为 `area: component: summary`，例如 `doc: clarify build prerequisites`、`boards: bes2700yp_devkit: describe BTH target`。前缀根据修改范围选择；可在集成仓内用 `git log -- path/to/file` 参考已有历史，不强制每条提交都带芯片名。
- 标题单行、少于 72 个字符，随后空一行；提交信息使用英文。
- 正文不能为空，说明问题、改动原因、必要假设和实际验证；通常每行不超过 75 个字符，长 URL 等可例外。
- 一个提交表达一个独立逻辑变化。提交评审前自查，整理临时 fixup 提交，避免混入无关格式调整或 merge 提交。
- 每个提交提供 [DCO](https://docs.zephyrproject.org/latest/contribute/guidelines.html#developer-certification-of-origin-dco) 的 `Signed-off-by`。自有提交使用与 Author 一致的真实姓名和真实邮箱；修改他人提交时保留原有签署，由实际贡献者追加自己的签署。
- DCO 由贡献者本人确认，确认后可用 `git commit -s` 添加签署。AI 或自动化工具不能代替贡献者作出认证或添加其签署；`Signed-off-by` 不是 GPG 签名，也不能代替第三方分发授权。
- 关联问题使用明确的仓库路径；外部依据可使用 `Link:`。
  PR 描述说明行为变化及验证结果，未执行的实板测试明确标记为待测。

以下仅为格式示例，签署身份必须替换为实际贡献者，正文必须反映实际改动与验证：

```text
doc: describe contribution requirements

Document the commit format and the repository validation workflow.
This gives contributors a consistent checklist before review.

Validation: checked document links and ran the repository checks.

Signed-off-by: Your Full Name <your.email@example.com>
```

## 分支与发布

本节的发布候选与标签管理由维护者执行；日常贡献按前面的开发与验证流程进行。

`main` 仅接收满足相关检查和验证要求的改动。需要多轮实板验证时使用临时 `release/*` 分支，不设置长期 `develop`。候选冻结前整理同一改动的临时修复，保留可独立评审的逻辑提交。

发布候选以固定提交、`vX.Y.Z-rcN` 标签及镜像 SHA256 标识。冻结后不再对该候选 rebase、squash 或修改提交信息；后续变更形成下一候选。冻结约定针对已标记的候选，不妨碍 `main` 和其他开发分支持续演进。

首次公开源码快照可以如实保留 `hardware: not_tested` 和 HAL `unconfirmed` 状态，但不得描述为已通过实板验证的固件，也不得将仓库公开视为厂商授权。已验证的固件发布还需完成关联该镜像 SHA256 的仓库检查、主机回归、干净构建、离线审计及实板验收，再将已验证的相同提交快进合入 `main` 并建立正式标签。若 `main` 已前进导致不能快进，应重新形成和验证候选。标签不移动，正式源码包和镜像对应同一集成仓提交、`west.yml` 指定的模块提交及 `hal-release.sha256` 对应的 HAL `manifest.json`；芯片支持范围以硬件说明及对应验证记录为准。

### 候选包来源

日常构建默认使用 `development` 模式，允许集成仓和 HAL 模块存在未提交的开发修改；构建包会归档实际文件并记录来源。正式候选在独立、干净的 checkout 中构建，向 west 构建命令添加 `-DBES_FORMAL_PACKAGE=ON`，或在[CI 构建命令](docs/testing.zh-CN.md#ci-入口)中添加 `--formal`。该模式要求集成仓和 HAL 模块来自固定、干净且构建期间不变的 Git 提交；Zephyr、CMSIS 和 CMSIS_6 也须符合锁定提交及工作区检查要求。

HAL 下载库不由 Git 跟踪，工作区干净不能代替库内容校验。正式归档分别核对固定提交中的文件和 blob 哈希，再将完整 HAL 文件纳入 `hal-consumer.tar`；构建期间任一 HAL 输入变化都会拒绝打包。

构建包的 `release/manifest.json` 记录归档模式，`release/source-provenance.json` 记录提交、工作区状态、文件哈希及 blob 下载元数据；源码归档文件见[构建产物与校验](docs/getting-started.zh-CN.md#构建产物与校验)。集成仓提交、`west.yml` 指定的模块提交或 `hal-release.sha256` 发生变化时，应重新构建候选包并生成来源记录，不修改旧包中的提交号。`formal` 只核对构建来源，实板结果和分发状态另行记录。
