# Domains — Spider 业务层

> Domains 定义 Spider **在研究什么**。属于业务层/信息层，不属于 spider_core 基础设施层。

## 分层原则

```
小蜘蛛/domains/     ← 业务层: sources, prompts, scoring, report style
spider_core/core/   ← 基础设施层: logger, retry, network, windows_utils
```

**Domain 负责**: sources、prompts、ranking logic、report style、topic logic
**Core 负责**: logger、retry、parser、scheduler、shared runtime utilities

不要让 spider_core 承担业务组织层。Core 与 Domain 边界须保持清晰。

## 当前 Domain

| Domain | 状态 | Pipeline | 描述 |
|--------|------|----------|------|
| [ai](./ai/) | active | two_stage | AI 前沿情报 — 23 源, 9 过滤标准, Python fetch + Claude 分析 |
| [cognition](./cognition/) | active | single_stage_claude | 认知精选 — 6 子领域, 3 日轮换, 从 每日认知精选 并入 |

## Domain 描述符结构

每个 domain 目录包含一个 `descriptor.json`，记录：

- **pipeline** — 入口文件、阶段角色
- **domain_specific** — sources、scoring、prompts、report 的 domain 专属配置
- **shared_runtime** — 引用了哪些 spider_core 模块和 patterns
- **notable_constraints** — 该 domain 的设计约束

## 新增 Domain 约定

- **情报/日报输出**：统一放在 `01_原始素材/情报中心/<domain名称>/`，不进 `02_我的知识库/`
- **知识库** (`02_我的知识库/`) 只放经过整理、提炼、沉淀后的长期知识资产
- 每个 domain 的 `config.json` → `obsidian.output_dir` 须遵循此约定

## 演化路径

```
多个独立项目
    ↓
发现重复能力
    ↓
共享 Runtime (spider_core)     ← 当前已完成
    ↓
形成 Domains                    ← 当前阶段
    ↓
最终形成 Spider Platform        ← 未来
```
