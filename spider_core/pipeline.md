# Spider Unified Pipeline

> 所有 Spider 信息流的统一处理管道定义。
> 每个项目可以跳过某些阶段，但不能重新定义阶段顺序或语义。

---

## 1. Pipeline 总览

```
FETCH → VALIDATE → DEDUPLICATE → SOURCE_SCORING → CLASSIFY
  → SUMMARIZE → RANK → GENERATE_REPORT → ARCHIVE → KNOWLEDGE_BASE
```

---

## 2. 各阶段定义

### Stage 0: FETCH — 数据采集

**职责**：从配置的源获取原始数据。

**输入**：source config（URL、type、weight、category）

**输出**：`List[RawItem]`，每项包含 title、link、description、published、source_name、source_tier

**Core 提供**：
- `core/fetchers/rss_fetcher.py`
- `core/fetchers/github_trending_fetcher.py`
- `core/fetchers/web_scraper.py`

**项目定义**：
- 具体使用哪些 fetcher
- 每个源的权重和分类
- 超时和重试策略的参数

**当前实现**：
- 小蜘蛛: `fetch_ai_news.py` 中的 FETCHERS dispatch（RSS、GitHub、博客爬虫等 5 种）
- 每日认知精选: 无此阶段（Claude 用 web_search 代替）

---

### Stage 1: VALIDATE — 数据验证

**职责**：过滤明显无效/损坏的数据。

**输入**：`List[RawItem]`

**输出**：`List[RawItem]`（仅有效项）+ `List[SourceHealth]`

**检查项**：
- title 非空且长度 > 10
- link 格式有效
- 不是 404/500 响应
- 源连接成功（记录 source_health）

**Core 提供**：
- `core/validators/basic_validator.py` — title/link 基本检查

**项目定义**：
- 额外的领域特定验证规则

**当前实现**：
- 小蜘蛛: `fetch_one()` 的 try/except 隔离 + source_health 记录
- 每日认知精选: 由 Claude 隐式完成

---

### Stage 2: DEDUPLICATE — 去重

**职责**：移除重复/高度相似的内容。

**输入**：`List[ValidItem]`

**输出**：`List[UniqueItem]` + 多源信号标记

**策略**：
- 基于 title 的标准化 key 精确去重
- 多源覆盖标记（同一事件被多个源报道 → 提升权重）

**Core 提供**：
- `core/dedup/redis_dedup.py` — Redis 双层去重管道（URL Bloom + SimHash 模糊去重），支持优雅降级
- `scoring/engine.py::deduplicate()` — title 标准化 + 多源计数（内存级别，供无 Redis 场景使用）

**项目定义**：
- 去重 key 的生成规则（默认：去除非字母数字，截断 80 字符）
- 多源信号的权重加成

**当前实现**：
- 小蜘蛛: `deduplicate_and_signal()` in fetch_ai_news.py
- 每日认知精选: 由 Claude 隐式完成

---

### Stage 3: SOURCE_SCORING — 源可信度评分

**职责**：根据来源权威性和内容相关性打分。

**输入**：`List[UniqueItem]`

**输出**：`List[ScoredItem]`（每项带 `_source_weight`、`_impact_score`、`_total_score`）

**评分维度**：
- 源层级权重（tier weight: official > tech_trends > community > media）
- 内容相关性（关键词命中）
- 质量过滤（低质量内容标记为负分）

**Core 提供**：
- `core/scoring/rule_engine.py` — 基于规则的关键词打分引擎

**项目定义**：
- 关键词列表和权重（领域特定）
- 最低分阈值
- 质量过滤模式（如 Reddit 低质量帖）

**当前实现**：
- 小蜘蛛: `compute_impact_score()` + `add_source_weight()` in fetch_ai_news.py，9 条过滤标准
- 每日认知精选: Claude 用三道过滤网（prompt 内规则）

---

### Stage 4: CLASSIFY — 分类

**职责**：将信息分配到领域/类别。

**输入**：`List[ScoredItem]`

**输出**：`Dict[Category, List[Item]]`

**分类维度**：
- 按领域（AI / 商业 / 心理学 / ...）
- 按类型（论文 / 产品 / 开源项目 / 新闻 / ...）
- 按影响类型（工作流 / 自动化 / 内容生产 / ...）

**Core 提供**：
- `core/classify/keyword_classifier.py` — 基于关键词的分类器

**项目定义**：
- 分类体系和规则

**当前实现**：
- 小蜘蛛: 无显式分类（依赖 Claude 在 Stage 2 做）
- 每日认知精选: 按 rotation domains 分类

---

### Stage 5: SUMMARIZE — 摘要

**职责**：将长文本压缩为核心要点。

**输入**：`List[ClassifiedItem]`

**输出**：`List[SummarizedItem]`（每项带 1-3 句摘要 + 关键词）

**当前实现**：
- 全部由 Claude 完成（这是 LLM 最擅长的部分）

**Core 当前不提供此阶段**（LLM 完成，非 Python 代码）。

---

### Stage 6: RANK — 排序

**职责**：根据综合得分和用户偏好排序，选出最终展示项。

**输入**：`List[SummarizedItem]`

**输出**：`List[RankedItem]`（top N，通常 4-8 条）

**Core 提供**：
- `core/ranking/score_sorter.py` — 基于 `_total_score` 的排序器

**项目定义**：
- top N 的数量
- 是否强制每个领域至少 1 条
- 是否提升特定类型（如官方公告 > 社区讨论）

**当前实现**：
- 小蜘蛛: `max_items_for_report` 截断（config.json）
- 每日认知精选: Claude 三道过滤后保留 4 条

---

### Stage 7: GENERATE_REPORT — 生成报告

**职责**：将排序后的信息生成格式化 Markdown 报告。

**输入**：`List[RankedItem]`

**输出**：写入 Obsidian vault 的 `.md` 文件

**Core 提供**：
- `core/renderer/markdown_writer.py` — YAML frontmatter + body 写入，带备份和原子写入
- `core/claude/cli_runner.py` — Claude CLI 调用封装

**项目定义**：
- 报告模板和风格
- YAML frontmatter 字段
- Section 组织和排版

**当前实现**：
- 小蜘蛛: Claude CLI 生成 → 直接写入。fallback 用 Python 字符串拼接
- 每日认知精选: Claude CLI 生成 → validate_output() → update_index()

---

### Stage 8: ARCHIVE — 归档

**职责**：保存原始数据和处理结果，用于回溯和重处理。

**输入**：原始 JSON + 生成的报告

**输出**：持久化到 `data/` 和 `logs/`

**Core 提供**：
- `core/logger.py` — 最小化日志

**项目定义**：
- 数据保留策略（多久清理一次）

**当前实现**：
- 小蜘蛛: data/ 保留原始 JSON，logs/ 保留运行日志
- 每日认知精选: logs/ 保留日志，无原始数据归档（Claude 搜索是即时的）

---

### Stage 9: KNOWLEDGE_BASE — 知识沉淀

**职责**：将报告中的关键信息结构化，纳入长期知识库。

**输入**：生成的报告

**输出**：更新索引文件、知识图谱、跨日统计

**当前实现**：
- 每日认知精选: `update_index()` 更新 `每日认知精选索引.md`
- 小蜘蛛: 无此阶段（报告本身即是最终产物）

**Core 当前不提供此阶段**（项目特定逻辑）。

---

## 3. Pipeline 实现模式

### 模式 A: Two-Stage (小蜘蛛)

```
Python: FETCH → VALIDATE → DEDUP → SOURCE_SCORING
       → (data saved to JSON)
Claude: CLASSIFY → SUMMARIZE → RANK → GENERATE_REPORT
Python: ARCHIVE
```

**适用**：数据采集量大（20+ 源），需要 Python 做预过滤和评分。

### 模式 B: Single-Stage Claude (每日认知精选)

```
Claude: FETCH(via web_search) → VALIDATE → DEDUP
       → CLASSIFY → SUMMARIZE → RANK → GENERATE_REPORT
Python: VALIDATE(via validate_output) → KNOWLEDGE_BASE(via update_index)
       → ARCHIVE
```

**适用**：依赖 Claude 的搜索能力，数据源较少或动态，需要 LLM 判断质量。

### 模式 C: 纯 Python Pipeline（未来）

```
Python: FETCH → VALIDATE → DEDUP → SOURCE_SCORING → CLASSIFY
       → SUMMARIZE(via local LLM) → RANK → GENERATE_REPORT
       → ARCHIVE → KNOWLEDGE_BASE
```

**适用**：完全离线、不依赖外部 LLM API、对延迟敏感的场景。

---

## 4. 项目如何声明 Pipeline

在项目级 CLAUDE.md 中声明：

```markdown
## Pipeline 声明

本项目的 Pipeline 实现：
- Python 负责: FETCH, VALIDATE, DEDUP, SOURCE_SCORING
- Claude 负责: CLASSIFY, SUMMARIZE, RANK, GENERATE_REPORT
- 跳过: KNOWLEDGE_BASE

使用的 Core 模块:
- core/logger
- core/network_wait
- core/windows_utils
```

**约束**：
- 可以跳过阶段（如跳过 KNOWLEDGE_BASE）
- 可以合并阶段（如 Claude 同时做 CLASSIFY + SUMMARIZE）
- 不能改变阶段顺序
- 不能重新定义阶段语义

---

## 5. 阶段间的数据契约

每个阶段的输出必须包含前一阶段的所有字段（只增不减），以便下游使用：

```python
# 基础字段（FETCH 产出，所有阶段保留）
{
    "id": str,
    "title": str,
    "link": str,
    "description": str,
    "published": str,
    "source_name": str,
    "source_tier": str,
}

# VALIDATE 增加
    "valid": bool,
    "source_health": {...},

# DEDUP 增加
    "_multi_source_count": int,

# SOURCE_SCORING 增加
    "_source_weight": int,
    "_impact_score": int,
    "_total_score": int,
    "_matched_criteria": [str],

# CLASSIFY 增加
    "category": str,
    "item_type": str,

# SUMMARIZE 增加
    "summary": str,
    "keywords": [str],

# RANK 增加
    "rank": int,
    "selected_for_report": bool,
```

---

> **维护规则**：新增 Pipeline 阶段需要更新本文档和 architecture.md。
