# Spider Domain Strategy

> One Spider, Multiple Domains — 领域扩展机制。

---

## 1. 核心原则

- **系统永远只有一个 Spider**
- 新领域 = 新的 domain pack，不是新的 Spider
- Domain pack 只负责领域特有的配置和内容，不重新实现基础设施
- Spider Core 的能力对所有 domain 通用

---

## 2. Domain Pack 结构

```
domains/
├── ai/                          ← 当前活跃
│   ├── domain.json              ← 领域元数据
│   ├── sources.json             ← 数据源配置
│   ├── filtering_criteria.json  ← 过滤标准
│   ├── prompt_template.md       ← 分析/策展提示词
│   └── report_style.md          ← 报告风格指南
│
├── cognition/                   ← 当前活跃
│   ├── domain.json
│   ├── rotation.json            ← 轮换配置（该 domain 特有）
│   ├── prompt_template.md
│   ├── quality_standards.md
│   └── report_style.md
│
├── business/                    ← 规划中
├── security/                    ← 规划中
├── psychology/                  ← 规划中
└── academic/                    ← 规划中
```

---

## 3. Domain Pack 职责边界

### 3.1 Domain pack 负责（每个 domain 可以不同）

| 项目 | 说明 | 示例 |
|------|------|------|
| **sources.json** | 数据源列表、类型、权重 | AI: 23 个源（RSS/GitHub/博客）；商业: 财经 RSS/竞品监控 |
| **filtering_criteria.json** | 内容过滤标准 | AI: 9 条（工作流/自动化/副业...）；心理学: 实验可复现性/效应量 |
| **prompt_template.md** | 分析/策展的系统提示词 | AI: "用通俗语言解释给非技术人员"；学术: "保持学术严谨，标注引用" |
| **report_style.md** | 报告格式、section 组织、排版风格 | AI: 五大分析模块；认知: 摘要+核心观点+行动建议 |
| **ranking strategy** | 排序偏好、领域覆盖规则 | 每个 domain 的源权重体系 |

### 3.2 Spider Core 负责（所有 domain 共用）

| 能力 | 来源 |
|------|------|
| 日志 | `core/logger.py` |
| 网络检查 | `core/network_wait.py` |
| Windows 环境修复 | `core/windows_utils.py` |
| 数据采集器（RSS、web scrape） | `core/fetchers/` |
| 通用去重 | `core/dedup/` |
| Claude CLI 调用 | `core/claude/` |
| 健康报告骨架 | `patterns/health_report.md` |
| 降级处理骨架 | `patterns/fallback.md` |

---

## 4. 如何新增一个 Domain

### Step 1: 创建 domain pack

```bash
mkdir -p domains/business
```

### Step 2: 编写 domain.json

```json
{
  "name": "business",
  "label": "商业情报",
  "description": "创业机会、市场信号、竞品动态、商业模式分析",
  "status": "active",
  "created": "2026-06-01",
  "output_dir": "02_我的知识库/每日商业情报",
  "rotation": null,
  "pipeline_mode": "two_stage"
}
```

### Step 3: 配置 sources.json

定义该领域的数据源（RSS、API、web scrape）。

### Step 4: 编写 prompt_template.md

该领域的分析规则和输出格式。

### Step 5: 在 registry.json 中注册

```json
"domains": {
  "business": {
    "path": "domains/business",
    "status": "active",
    "pipeline_mode": "two_stage"
  }
}
```

### Step 6: 创建项目目录

```
all_my_projects/商业情报/
├── CLAUDE.md           ← 声明 domain = business, pipeline_mode = two_stage
├── main.py             ← 项目 orchestrator（引用 core/ 模块）
└── config.json         ← 指向 domains/business/sources.json
```

**检查清单**：
- [ ] 是否从 spider_core 复用了 logger、network_wait、windows_utils？
- [ ] 是否使用统一的 pipeline 阶段？
- [ ] 是否在 registry.json 中注册了新 domain？
- [ ] 项目 CLAUDE.md 是否声明了 domain 和 pipeline_mode？

---

## 5. 当前 Domain 状态

### 活跃

| Domain | 项目 | Pipeline | 状态 |
|--------|------|----------|------|
| **ai** | 小蜘蛛 | two_stage (Python+Claude) | 运行中，v0.3 |
| **cognition** | 每日认知精选 | single_stage (Claude-only) | 运行中，3 领域轮换 |

### 规划中

| Domain | 价值 | 复杂度 | 优先级 |
|--------|------|--------|--------|
| **business** | 创业机会扫描、竞品监控、商业模式分析 | 中（需要商业 RSS + 财经数据 API） | 按需 |
| **psychology** | 认知科学、行为经济学、心理健康研究 | 低（主要是期刊 RSS） | 低 |
| **security** | 网络安全动态、CVE 监控、工具链更新 | 中（需要 CVE 数据库 + 安全博客） | 低 |
| **academic** | 论文追踪、引用分析、跨学科信号 | 高（需要 Semantic Scholar/arXiv API） | 低 |

---

## 6. Domain 间信号交叉

当多个 domain 同时讨论同一事件时，触发跨域信号：

```
AI domain + Business domain 都提到 "AI 编程助手市场增长"
→ 自动标记为 [跨域信号]
→ 提升到更高优先级的综合情报
```

这是 Stage 3 (自动化认知层) 的能力，当前尚未实现。

---

## 7. 反模式

### 禁止：复制项目创建新领域

```
❌ cp -r 小蜘蛛/ 商业蜘蛛/  # 复制整个项目
❌ 修改商业蜘蛛/config.json    # 只改配置
```

### 正确：引用 Core，只写领域特有内容

```
✅ 创建 domains/business/  # 领域配置
✅ 创建 商业情报/main.py    # 引用 core/ 模块，~50 行
✅ 商业情报/CLAUDE.md       # 声明 domain + pipeline
```

---

> **维护规则**：新增 domain 后更新本文档和 registry.json。
