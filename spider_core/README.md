# Spider Core Framework v2

Spider 的个人 Cognitive Infrastructure System。管理可复用的核心模块、设计模式、领域包和项目注册。

## 快速导航

| 文档 | 用途 |
|------|------|
| [SPIDER_CONSTITUTION.md](./SPIDER_CONSTITUTION.md) | 框架宪章 v2 — One Spider, Multiple Domains |
| [architecture.md](./architecture.md) | 架构评估 — 当前能力、风险、演化路线 |
| [lifecycle.md](./lifecycle.md) | 能力生命周期 — candidate → experimental → stable → deprecated |
| [pipeline.md](./pipeline.md) | 统一 Pipeline — 10 阶段定义与契约 |
| [domain_strategy.md](./domain_strategy.md) | Domain Pack 机制 — 如何扩展新领域 |
| [registry.json](./registry.json) | 能力注册表 — 所有模块、候选、领域 |

## 目录结构

```
spider_core/
├── SPIDER_CONSTITUTION.md   ← 框架宪章 v2
├── README.md                ← 本文档
├── architecture.md          ← 架构评估与演化路线
├── lifecycle.md             ← 能力生命周期管理
├── pipeline.md              ← 统一 Pipeline 定义
├── domain_strategy.md       ← Domain Pack 机制
├── registry.json            ← 能力注册表
├── core/                    ← 正式 Core 模块（待创建）
├── domains/                 ← 领域包（待创建）
└── patterns/                ← 设计模式文档（待创建）
```

## 新项目接入

1. 阅读 [SPIDER_CONSTITUTION.md](./SPIDER_CONSTITUTION.md)
2. 阅读 [architecture.md](./architecture.md) 了解当前能力
3. 检查 [registry.json](./registry.json)，确认已有能力
4. 优先从 `core/` 引入已有模块
5. 项目完成后，标注新发现的通用能力为 Candidate

## 新增领域

1. 阅读 [domain_strategy.md](./domain_strategy.md)
2. 创建 `domains/<name>/` 目录
3. 编写 domain.json + sources.json + prompt_template.md
4. 在 registry.json 中注册
5. 创建项目目录，引用 core/ 模块

## 贡献 Core 模块

1. 当代码在 2+ 项目中几乎相同时，标记为 Candidate
2. 在 registry.json 中添加 candidate 条目
3. 参考 [lifecycle.md](./lifecycle.md) 判断抽离时机
4. 用户确认后，抽离到 core/ 并更新 registry

## 当前状态

- **Core 模块**: 0 个已抽离，4 个 Candidate 待抽离
- **活跃项目**: 2（小蜘蛛、每日认知精选）
- **活跃领域**: 2（AI、Cognition）
- **下一动作**: 抽离 logger、network_wait、windows_utils 到 core/
