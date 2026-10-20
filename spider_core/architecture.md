# Spider Architecture — 架构评估与演化路线

> [!WARNING]
> **本文档是 2026-05-24 的规划快照，§1–§5 的多数内容已被实际执行推翻，不要据它判断现状。**
> 保留原文是为留下决策痕迹（尤其 §5 ADR-001 的到期条件），不作当前事实来源。
>
> 已确认过时的部分（2026-09-21 复核）：
>
> | 本文档说法 | 实际情况 |
> |---|---|
> | §1.1 第 17 行「core/ 尚未创建 — 无已抽离模块」 | `spider_core/core/` 已建成：logger / network_wait / windows_utils / dedup / renderer / structured_logger / output_utils / domain_status / dashboard，另有 `spider_core/scoring/engine.py` |
> | §1.1 把 `每日认知精选/` 画成兄弟项目 | 已并入 `小蜘蛛/domains/cognition/`，顶层不再存在该目录 |
> | §1.1 的 `小蜘蛛/` 树（含 `logger.py`） | 无 `logger.py`（已抽离）；且缺 `spider_launcher.py`、`domains/`、`lib/`、守护脚本等。**以 `小蜘蛛/CLAUDE.md` 的树为准** |
> | §1.1 第 20 行「23 源采集」 | 20 源（Reddit 限流删 3 源，见 `小蜘蛛/config.json`） |
> | §2「可立即抽离为 core/」、§3「core/ 为空（高）」、§4 Phase 1「本周创建 core/」 | 均已执行完毕 |
> | §4 Phase 3「创建 domains/ai/、domains/cognition/」 | 已执行完毕 |
> | §1.1 第 27 行 `generate_report.ps1` | 文件仍在，但第 20 行读不存在的 `AI前沿信息情报官\config.json`，因 `$ErrorActionPreference="Stop"` 当场终止 —— 永远走不到第 86 行，属死文件（见 `小蜘蛛/AUDIT_2026-09-21.md`） |
>
> 唯一仍然成立的：ADR-002（`sys.path.insert` 而非 pip package，2026-10-19 合并后仍沿用该机制，只是路径由 `BASE_DIR.parent` 改为 `BASE_DIR`）。

> [!NOTE]
> **2026-10-19 布局变更**：`spider_core/` 已从 `all_my_projects/` 的平级目录移入 `小蜘蛛/spider_core/`，
> 与实例项目合并为单一仓库。§1.1 的树形图作废；当前布局见 `小蜘蛛/README.md` 的「目录结构」。
> `spider_core/.git`（7 个 commit）已移至 `D:\.claude\backups\spider_core-git-20261019` 保留历史。

> 2026-05-24 · 基于 Spider Constitution v2

---

## 1. 当前架构快照

### 1.1 项目布局

```
all_my_projects/
├── spider_core/                    ← L2 框架层（本文档所在）
│   ├── SPIDER_CONSTITUTION.md      ← Constitution v2
│   ├── registry.json               ← 能力注册表
│   ├── README.md
│   └── (core/ 尚未创建 — 无已抽离模块)
│
├── 小蜘蛛/                         ← L3 项目：AI 前沿情报官
│   ├── fetch_ai_news.py            ← Stage 1: 23 源采集 + 9 标准过滤
│   ├── generate_report.py          ← Stage 2: Claude CLI 编排器
│   ├── build_prompt.py             ← Prompt 构建（已被 generate_report 内联取代）
│   ├── logger.py                   ← 日志（与 每日认知精选 完全相同）
│   ├── version.py                  ← 版本追踪
│   ├── config.json                 ← 源配置 + 过滤标准
│   ├── prompt_template.md          ← 分析规则模板
│   └── generate_report.ps1         ← PowerShell 入口（遗留）
│
└── 每日认知精选/                   ← L3 项目：认知精选日报
    ├── curate_daily.py             ← 单阶段 Claude 编排器
    ├── logger.py                   ← 日志（与 小蜘蛛 完全相同）
    ├── config.json                 ← 轮换配置 + 质量标准
    └── prompt_template.md          ← 策展规则模板
```

### 1.2 数据流（当前）

```
小蜘蛛:
  config.json → fetch_ai_news.py → data/ai_news_raw_*.json
             → generate_report.py → Claude CLI → Obsidian vault

每日认知精选:
  config.json → curate_daily.py → Claude CLI (web_search) → Obsidian vault
```

---

## 2. 当前能力成熟度评估

### 2.1 成熟能力（可立即抽离为 core/）

| 能力 | 状态 | 证据 | 接口 |
|------|------|------|------|
| **logger** | stable | 两个项目逐字节相同，已稳定运行 | `log(msg: str) -> None` |
| **network_wait** | stable | 两个项目逐字节相同，参数化一致 | `wait_for_network(host, port, timeout) -> bool` |
| **merge_user_path** | stable | 两个项目逐字节相同，Windows 特定 | `merge_user_path() -> None` |

### 2.2 候选能力（近成熟，需微调后抽离）

| 能力 | 状态 | 差异 | 建议 |
|------|------|------|------|
| **read_claudian_config** | candidate | 小蜘蛛内联在 main()；每日认知精选 独立函数。逻辑相同，结构不同 | 统一为 `read_claudian_config(vault_path) -> (str, dict)` |
| **claude_cli_runner** | candidate | 两个项目都有 subprocess.run 调用 Claude CLI，参数模式一致 | 抽离为 `run_claude(prompt, output_dir, effort) -> int` |
| **health_report** | candidate | 小蜘蛛 用 spider_health_report()；每日认知精选 用 print_health()。输出格式不同但语义相同 | 记录到 patterns/，暂不抽离代码 |
| **fallback_generator** | candidate | 两个项目都有 Claude 失败时的降级逻辑 | 记录到 patterns/，提供通用骨架 |

### 2.3 不应抽离的能力

| 能力 | 原因 |
|------|------|
| **source_scoring** | 目前仅 小蜘蛛 使用。语义与项目强绑定（9 条过滤标准是 AI 领域特定的）。等第二个 domain 出现类似需求时再评估 |
| **obsidian_writer** | 两个项目向 Obsidian 写入但格式完全不同（YAML frontmatter 结构不同、section 组织不同）。通用部分太薄（只是 `Path.write_text()`），不值得单独抽模块 |
| **build_prompt** | 已被 generate_report.py 内联取代，属于遗留代码。不应抽离 |
| **version.py** | 仅 小蜘蛛 使用。逻辑简单（正则 + 文件写入），不到 100 行。等第二个项目需要版本追踪时再评估 |
| **index_updater** | 每日认知精选 特有逻辑（解析文章 → 更新索引表）。与其他项目无关 |
| **output_validator** | 每日认知精选 特有（检查 YAML、domain sections、article count）。验证规则与项目 prompt 模板强绑定 |

---

## 3. 架构风险

### 3.1 当前风险

| 风险 | 严重度 | 说明 |
|------|--------|------|
| **代码重复** | 高 | logger.py 在两个项目中逐字节相同。任何 bug 修复需要改 2 处 |
| **core/ 为空** | 高 | registry.json 标记了 7 个 candidate，但 core/ 目录不存在，零个已抽离。Constitution 的复用原则无法执行 |
| **无统一入口** | 中 | 两个项目的 orchestrator (generate_report.py, curate_daily.py) 都从零开始实现：网络检查、PATH 修复、配置读取、Claude CLI 调用。新项目需要复制 ~80 行样板代码 |
| **registry 过时风险** | 中 | registry.json 当前准确，但没有自动化检查机制。随着项目增加，registry 可能与实际代码不同步 |
| **prompt 模板紧耦合** | 低 | prompt_template.md 与 Claude CLI 调用深度绑定。换用其他 LLM 需要大量重写 |

### 3.2 长期扩展风险

| 风险 | 严重度 | 说明 |
|------|--------|------|
| **领域爆炸** | 高 | 如果直接复制 小蜘蛛/ 创建 商业蜘蛛/、安全蜘蛛/，6 个月后会有 5+ 个 90% 相同的代码库，任何改进需要改 5 处 |
| **Pipeline 碎片化** | 高 | 小蜘蛛 是 two-stage Python+Claude；每日认知精选 是 single-stage Claude-only。没有约束的情况下，第 3 个项目可能发明第三种 pipeline，导致无法统一维护 |
| **Core 膨胀** | 中 | 随着 candidate 增多，如果抽离标准不严格，core/ 可能塞满只有一个用户的小工具 |
| **Constitution 腐化** | 中 | 项目紧急需求可以覆盖 Constitution（按冲突优先级规则），但如果豁免声明不规范，Constitution 会名存实亡 |
| **配置漂移** | 低 | config.json 格式没有 schema 约束。未来 5+ 个 domain pack 可能有 5 种不同的配置结构 |

---

## 4. 下一阶段演化建议

### Phase 1: 巩固核心（本周）

**目标**：让 spider_core 真正可用

1. **创建 core/ 并抽离 3 个 stable 模块**
   - `core/logger.py` — 从 小蜘蛛/logger.py 抽离
   - `core/network_wait.py` — 从 generate_report.py 抽离
   - `core/windows_utils.py` — merge_user_path + read_claudian_config
   
2. **更新两个项目**：将 import 改为从 spider_core 引入
   
3. **更新 registry.json**：将 3 个模块状态从 candidate → stable

### Phase 2: 统一 Pipeline（下周）

**目标**：新项目不再从零写 orchestrator

1. **创建 `core/pipeline_runner.py`** — 统一编排器骨架
   - 网络检查 → PATH 修复 → 配置读取 → 执行 → 健康报告
   - 项目通过 hook/callback 注入自己的逻辑
   
2. **创建 `patterns/` 目录**，记录 health_report 和 fallback 模式

### Phase 3: Domain Pack 机制（按需）

**目标**：支持第一个非 AI 领域

1. 创建 `domains/ai/` — 将 小蜘蛛 的 config + prompt 迁移进去
2. 创建 `domains/cognition/` — 将 每日认知精选 的 config + prompt 迁移进去
3. 验证 "新增领域不改 Core" 的约束是否可行

### Phase 4: 能力系统成熟（长期）

**目标**：自文档化、自检查

1. registry.json 自动一致性检查（CI 或 pre-commit hook）
2. config.json schema 约束
3. 能力使用统计（哪些 core 模块被哪些项目使用）

---

## 5. 架构决策记录

### ADR-001: 为什么 core/ 至今为空

**决策**：暂时不从项目内联代码中抽离。

**原因**：
- 两个项目都在快速迭代中，过早抽离可能导致接口频繁变化
- 当前只有 2 个 Spider 项目，复用压力不大
- 等待第三个项目出现时，可以更准确地判断什么是真正的通用接口

**到期条件**：第三个 Spider 项目创建时，必须完成 core/ 抽离。

### ADR-002: 为什么不用 package 形式

**决策**：使用 `sys.path.insert` 而非 pip install。

**原因**：
- Spider Core 只在本地使用，不需要分发
- 用户环境是 Windows + Task Scheduler，pip package 增加环境复杂度
- 直接路径引用更透明、更易调试

---

> **维护规则**：本文档在每次架构变更后更新。重大变更需用户确认。
