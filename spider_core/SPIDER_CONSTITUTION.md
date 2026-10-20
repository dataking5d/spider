# Spider Global Constitution v2

> Spider 不是单一项目，而是长期运行、持续成长、跨项目复用的 **Cognitive Infrastructure System**。
> 本宪章约束所有 Spider 项目、自动化系统、信息采集项目。

---

## 1. Spider 长期定位

Spider 的本质不是某个具体项目，而是：**信息获取 → 信息处理 → 信息沉淀 → 自动化认知流转** 的基础设施。

### Spider 负责

- 信息采集、过滤、来源可信度分析
- 自动摘要、知识沉淀、自动化情报流
- 长期知识积累、多项目信息支持

### Spider 最终目标

建立 **Personal Cognitive Operating System** — 长期运行的：
- 信息采集层
- 信息处理层
- 自动化认知层
- AI 知识流系统

未来任何复杂项目，只要涉及信息获取、数据分析、AI 摘要、自动化知识流，都应优先调用 spider_core 而不是重新开发。

---

## 2. 核心架构原则：One Spider, Multiple Domains

**系统永远只有一个 Spider。**

未来领域（AI / 商业 / 学术 / 安全 / 心理学）都只是 **domain packs**，不是新 Spider。

**禁止**：每新增领域重新造一个 Spider。

参见 [domain_strategy.md](domain_strategy.md)。

---

## 3. 系统分层

```
┌──────────────────────────────────────────┐
│ L1: Global Layer (D:\.claude\CLAUDE.md)  │
│     编码哲学、用户协同、稳定性、归档       │
├──────────────────────────────────────────┤
│ L2: Spider Constitution Layer            │
│     spider_core/                         │
│     - SPIDER_CONSTITUTION.md (本文档)     │
│     - registry.json                      │
│     - core/ (正式模块)                    │
│     - domains/ (领域包)                   │
│     - architecture.md                    │
│     - lifecycle.md                       │
│     - pipeline.md                        │
│     - domain_strategy.md                 │
├──────────────────────────────────────────┤
│ L3: Project Layer                        │
│     项目级 CLAUDE.md                      │
│     项目目标、domain、source 配置          │
│     prompt 风格、输出格式、项目特殊逻辑    │
└──────────────────────────────────────────┘
```

### 各层职责

| 层级 | 负责 | 禁止 |
|------|------|------|
| L1 Global | 编码哲学、跨项目通用规则 | 写项目逻辑 |
| L2 Spider Core | Constitution、registry、core 模块、pipeline、生命周期 | 写具体项目配置 |
| L3 Project | 项目目标、domain、source、prompt、输出格式 | 重新实现 Spider Core |

### 冲突优先级

**项目紧急需求 > Spider Constitution > 全局 CLAUDE.md**

但与 Constitution 冲突的决策必须在项目 CLAUDE.md 中显式声明豁免及原因。

---

## 4. 能力生命周期机制

任何能力，如果满足以下任一条件，自动标记为 `[Spider Core Candidate]`：

- 被 2 个以上项目复用
- 具有长期通用价值（不依赖特定项目上下文）

### 生命周期状态

```
candidate → experimental → stable → deprecated
```

- **candidate**: 被识别为通用能力，待评估
- **experimental**: 已抽离到 core/，接口可能变化
- **stable**: 接口稳定，多项目使用，向后兼容
- **deprecated**: 有更好的替代，保留 2 个版本周期后移除

### 状态流转规则

详见 [lifecycle.md](lifecycle.md)。

### registry.json 维护

- 所有 core 模块和 candidate 必须在 registry.json 中登记
- 每次状态变更必须更新 registry.json
- registry.json 是新建项目时的第一查阅点

---

## 5. Core 抽离原则

### 抽离标准

一个能力值得抽离到 core/ 当：
- 逻辑在 2+ 项目中几乎相同（非巧合）
- 抽离后接口稳定（预计不会频繁变化）
- 抽离不影响现有项目运行
- 模块足够小且职责单一

### 不抽离的情况

- 逻辑相似但语义不同
- 只是一个代码片段（< 20 行）
- 只在同一项目内复用的内部工具

### 抽离的不是代码，是稳定接口

```python
# 正确：稳定导入
from spider_core.core.logger import SpiderLogger

# 错误：复制文件
# cp ../小蜘蛛/logger.py ./logger.py
```

---

## 6. Reuse Before Rewrite

未来任何新项目，开始前必须：

1. 扫描 `spider_core/`
2. 读取 `registry.json`
3. 检查已有能力
4. 优先复用

**禁止**：重复造轮子。只有现有能力无法满足需求时，才允许新增实现。

---

## 7. Extract Before Expand

新增领域前，优先抽离稳定核心能力。

例如：先稳定 logger、retry、source_runner、health_report，再扩展 AI、商业、安全、学术。

避免功能爆炸后无法维护。

---

## 8. 统一 Pipeline 原则

所有 Spider 信息流统一进入：

```
fetch → validate → deduplicate → source_scoring → classify
→ summarize → rank → generate_report → archive → knowledge_base
```

**禁止**：每个项目重新设计流程。

详见 [pipeline.md](pipeline.md)。

---

## 9. 用户协同原则

### 必须询问用户的操作

| 类别 | 具体操作 |
|------|---------|
| Scheduler | 创建/修改/删除 Windows Task Scheduler 任务 |
| 权限 | 需要管理员权限的任何操作 |
| 系统 | 修改系统配置、环境变量、注册表 |
| 删除 | 删除 Spider Core 文件或项目核心文件 |
| 长期逻辑 | 改变定时任务的运行频率、触发条件 |
| 自动化策略 | 改变数据源权重、过滤标准、输出目标 |
| 架构调整 | 架构级变更、Core 模块删除、生命周期大改 |

### 可自主执行的操作

- 读取文件、分析日志
- 在项目目录内创建/修改代码
- 修复明显的 bug
- 添加日志输出
- 低风险优化（不改变行为）
- 标记 Candidate

### 失败处理

如果方案失败：
- 必须解释原因
- 给出替代方案
- 等待用户确认
- **禁止静默切换实现方案**

---

## 10. 稳定性优先原则

### 优先级排序

**稳定性 > 长期运行 > 可恢复 > 可观察 > 可维护 > 功能扩展**

### 四条铁律

1. **可恢复**：任何失败不丢数据，有备份或重试路径
2. **可观察**：关键路径有日志，静默失败不可接受
3. **可维护**：6 个月后不需要重新理解才能修改
4. **可隔离**：单模块失败不导致系统级崩溃

### 功能准入门槛

新增功能不能降低现有系统稳定性。如果新功能引入不可恢复的失败路径，不允许上线。

---

## 11. Domain Pack 机制

未来领域扩展统一放入 `domains/`：

```
domains/
├── ai/            ← 当前活跃
├── business/      ← 规划中
├── security/      ← 规划中
├── psychology/    ← 规划中
└── academic/      ← 规划中
```

每个 domain 只负责：
- source config（数据源配置）
- prompts（分析提示词）
- ranking strategy（排序策略）
- report style（报告风格）

Domain 不负责输出与记忆机制 — 输出引擎由 `core/renderer/` 统一提供，
趋势记忆由 `core/memory/` 统一提供，通过 `domain` 参数自动路由到四层结构
（logs / health / reports / memory），保持跨 domain 对称。

**禁止**：重新实现 Spider Core。

详见 [domain_strategy.md](domain_strategy.md)。

---

## 12. 附录：当前 spider_core 目录结构

```
spider_core/
├── SPIDER_CONSTITUTION.md   ← 本文档 (v2.3)
├── README.md                ← 框架使用指南
├── architecture.md          ← 架构评估与演化路线
├── lifecycle.md             ← 能力生命周期管理
├── pipeline.md              ← 统一 Pipeline 定义
├── domain_strategy.md       ← Domain Pack 机制
├── registry.json            ← 能力注册表 (v2.7)
├── core/                    ← 正式 Core 模块（已抽离）
│   ├── logger.py            ← 共享日志引擎 + domain-aware routing
│   ├── structured_logger.py ← 结构化日志引擎 (structlog)
│   ├── network_wait.py      ← 网络可用性检查
│   ├── windows_utils.py     ← Windows PATH + Claudian 配置
│   ├── renderer/            ← 共享输出引擎
│   │   ├── markdown_writer.py
│   │   └── health_writer.py
│   ├── memory/              ← 长期记忆引擎 (v2.7 新增)
│   │   └── trend_memory.py
│   └── dedup/               ← 去重引擎 (candidate)
│       └── redis_dedup.py
├── scoring/                 ← 共享评分引擎
│   └── engine.py
├── domains/                 ← 领域包
└── patterns/                ← 设计模式文档（非代码）
```

### Four-layer runtime structure

```
{project}/
├── logs/          ← L1: Telemetry — raw event stream
│   ├── ai/
│   │   ├── YYYY-MM-DD.log        ← plain-text event log
│   │   └── YYYY-MM-DD.jsonl      ← structured event log
│   └── cognition/
│       ├── YYYY-MM-DD.log
│       └── YYYY-MM-DD.jsonl
├── health/        ← L2: Observability — aggregated runtime status
│   ├── ai/
│   │   └── YYYY-MM-DD-health.json
│   └── cognition/
│       └── YYYY-MM-DD-health.json
├── reports/       ← L3: Intelligence — human-readable output
│   ├── ai/
│   │   └── YYYY-MM-DD-ai.md
│   └── cognition/
│       └── YYYY-MM-DD-cognition.md
└── memory/        ← L4: Long-term Memory — incremental trend tracking
    ├── ai/
    │   └── trends.json
    └── cognition/
        └── trends.json
```

| Layer | Directory | Content | Engine |
|-------|-----------|---------|--------|
| L1 Telemetry | `logs/` | task start, fetch start, source failed, scoring done | `core/logger.py` + `core/structured_logger.py` |
| L2 Observability | `health/` | source uptime, failures, runtime, retries, score distribution | `core/renderer/health_writer.py` |
| L3 Intelligence | `reports/` | AI trends, cognition curation, event analysis | `core/renderer/markdown_writer.py` |
| L4 Memory | `memory/` | recurring topics, entities, themes, trend direction, frequency deltas | `core/memory/trend_memory.py` |

All four layers share: domain-aware routing, atomic writes, `{domain}` subdirectory symmetry.

---

> **版本**：v2.3 — 2026-05-27
> **上一版本**：v2.2 — 2026-05-27
> **变更**：新增 L4 Memory 层 — domain-local incremental trend memory，追踪 recurring topics/entities/themes 频率变化与趋势方向
> **维护规则**：本文档的修改需要用户确认
