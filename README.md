# 小蜘蛛 · AI 前沿情报系统

> 20 个信息源，压成每天一份可执行的 AI 判断。
> A daily AI-intelligence pipeline: 20 sources in, one actionable brief out.

## 这是什么

**不是新闻聚合器，而是 AI 趋势情报系统。**

只筛选真正会影响普通人工作、赚钱、效率、内容生产、自动化的 AI 动态。绝大多数
AI 新闻与个人无关，系统的价值在于**丢弃**：先按来源层级和 9 条标准打分，再由
Claude 在严格的质量规则下写成可行动的日报。Python 负责采集、评分、去重与事件
聚类（可复现、可测试），Claude 只在给定材料内筛选与撰写，不做事实发明。

## 系统设计

### 六层数据源

| 层级 | 来源 | 权重 | 目标 |
|------|------|------|------|
| Tier 1 | OpenAI / Anthropic / Google DeepMind / Meta AI / HuggingFace Blog / Microsoft Research | 100 | 第一时间发现真正的 AI 能力变化 |
| Tier 2 | Hacker News / GitHub Trending / Papers with Code / Google News AI | 70 | 发现真正开始落地的 AI 能力 |
| Tier 3 | Reddit r/LocalLLaMA / r/ClaudeAI | 55 | 观察真实使用反馈与工作流 |
| Tier 4 | Product Hunt | 50 | 发现快速商业化的 AI 工具 |
| Media | MIT Tech Review / TechCrunch / The Verge / VentureBeat | 40 | 补充视角 |
| Chinese | 量子位 / 雷锋网 AI科技评论 / 36氪 | 30 | 中文语境 |

共 **20 个 feed**。每源的**抓取**上限见 `sources.<tier>.max_items_per_source`，
进入**报告**的每源上限见 `filtering_criteria.report_max_per_source`（两者不同）；
上表权重是层级均值，单源以各 feed 的 `weight` 为准。

### 九条过滤标准

| 标准 | 权重 |
|------|------|
| 会改变普通人工作流 | 20 |
| 会提升生产效率 | 20 |
| 会推动 AI 自动化 | 20 |
| 会降低创业门槛 | 20 |
| 会改变内容生产方式 | 15 |
| 会产生新副业机会 | 15 |
| 会影响未来职业结构 | 15 |
| GitHub / 社区开始快速增长 | 10 |
| 多个高质量源同时讨论 | 10 |

`config.json` 声明 `minimum_criteria_score = 15`，即命中权重之和需达到 15；最弱的
单条标准只有 10 分，单独命中过不了闸。但该字段当前没有任何代码读取，实际闸门是
`domains/ai/scoring_config.json` 的 `min_relevance_score = 10`，两者不一致，见
「已知限制」。

评分后还会经过：低质量过滤、五维打分（信源权威 / 时效 / 社区热度 / 用户相关 /
长期价值）、URL 与 SimHash 去重、多源共振加权、近 7 天已发表来源去重、同 URL 与
同标题事件聚类，最终硬截断至 16 条候选，写入 `data/ai_news_raw_YYYY-MM-DD.json`。

## 快速开始

Python 3.13 实测通过。第三方依赖 `feedparser`、`requests`、`beautifulsoup4`，
`redis` 可选（跨天去重，不可用时自动降级放行）。未提供 `requirements.txt`：

```bash
pip install feedparser requests beautifulsoup4
```

另需一项内部条件：仓库内的 `spider_core/` 子目录（`generate_report.py` 等通过
`sys.path.insert(0, BASE_DIR / "spider_core")` 加载 `core.*` 与 `scoring.*`，
无需额外下载），以及可用的 Claude CLI（Stage 2 以 `--print --permission-mode dontAsk`
调用，模型由 `core.windows_utils.resolve_model()` 决定）。

### 配置数据源

先复制配置模板，再按自己的环境修改：

```bash
cp config.example.json config.json
```

编辑 `config.json`：`sources.*.feeds` 增删源与调整 `weight`；`filtering_criteria`
控制 9 条标准权重与报告条数；`obsidian.vault_path` 改成自己的 vault 绝对路径；
`redis_dedup.enabled` 在无 Redis 时设为 `false`。该文件不含任何 API Key 或令牌，
可安全入库。

### 单次运行

```bash
# 仅采集：20 个 feed → 评分去重 → data/ai_news_raw_YYYY-MM-DD.json
python fetch_ai_news.py
# 完整流程：采集 + Claude 分析 + 写入 Obsidian（当日已生成则跳过）
python generate_report.py
# 强制重跑：跳过「当日已生成」检查，输出文件自动加序号
python generate_report.py --manual
# 编排入口：并行拉起 task_registry.json 中的各 domain
python spider_launcher.py --verbose
```

`spider_launcher.py` 无参数时静默写 `logs/launcher/`，加 `--verbose` 输出到控制台。

### 接入定时任务

每日流程由 **WorkBuddy 自动化托管，12:00 触发**；12:30 另有飞书推送兜底任务，用当日
幂等键避免重复发卡片。本地 Windows 计划任务（`Spider晨跑`）已禁用，仅保留注册信息
用于回滚；不要新建本地计划任务或依赖守护进程触发管道。`spider_daemon.py` 只维持
8765 端口的看板，与调度无关。补跑由 WorkBuddy 发起，或手工执行上面的命令。

## 目录结构

```
小蜘蛛/
├── spider_launcher.py      编排入口：读 task_registry.json 并行跑各 domain
├── fetch_ai_news.py        AI Stage 1：采集 → 评分 → 去重 → 事件聚类
├── generate_report.py      AI Stage 2：组 prompt → Claude CLI → 验收 → 写 Obsidian
├── push_feishu.py          报告推送飞书（**不入库**：含私有群 chat_id，本地保留）
├── config.example.json     数据源 / 权重 / 9 条过滤标准（模板，可入库）
├── config.json             本机副本：填自己的 vault 路径（不入库，已 gitignore）
├── task_registry.json      domain 任务表与超时上限
├── prompt_template.md      报告输出模板
├── QUALITY_RULES.md        内容质量与措辞规则
├── domains/
│   ├── ai/                 actionability.py、event_merger.py、project_extractor.py、
│   │                       user_relevance.py、campus_detector.py、scoring_config.json
│   ├── cognition/          认知精选 domain：curator.py、prompt_template.md
│   └── claim_checks.py     断言与措辞校验
├── spider_core/            共享运行时：core/（日志、网络等待、证据抓取、Windows 工具）、
│                           scoring/（评分引擎）、patterns/，以及框架宪章与架构文档
├── tests/                  12 个 unittest 文件（采集、发布、证据、CLI 工具范围）
├── data/                   原始抓取 JSON，按日保留（不入库）
├── reports/                本地报告备份 reports/<domain>/（历史文件仍在版本库）
├── logs/  health/          结构化日志与健康状态，按 domain 分目录（不入库）
├── memory/                 ACP 记忆与运行时趋势记忆（JSON 不入库）
└── .workbuddy/             WorkBuddy 执行记录与自动化状态（不入库）
```

## 产出形态

每天产出一份 Markdown 报告，写入 Obsidian 的
`01_原始素材/情报中心/每日AI情报/YYYY-MM-DD_AI情报.md`。

结构为「今日重点 / 简讯 / 今晚行动」，报告内最多 8 条，单源最多 4 条，总字数上限
15000。每条需标注来源与证据范围（正文摘录 / 转发摘要 / 仅标题），证据不足时允许
少写或明确写「本轮无合格内容」。同一份内容另以飞书卡片推送。

报告**不入库**，原始 JSON 也不入库（`data/` 已在 `.gitignore` 中）。本仓库目前
**没有 `examples/` 目录，也没有提交样例报告**；如需展示，建议后续手工挑选 2–3 份
脱敏后放入 `examples/`。`reports/` 下的历史报告是早期提交，仍在版本库中，待后续
单独清理，本次整理未删除任何文件。

## 已知限制

- **36氪为空源**：feed 返回 200 但 0 条。已测试全部替代端点，唯一有内容的
  `feed-newsflash` 是财经快讯流，会把股市公告注入日报，因此宁可保留诚实的空源。
- **Reddit 配额**：匿名 `.rss` 实测约每窗口 2 个请求，Tier 3 只保留 2 个源；加到第 3
  个会让三者随机有一个被限流。若配额继续收紧，正确做法是减源而非加 sleep。
- **闸门配置不一致**：`minimum_criteria_score = 15` 无人读取，实际生效的是
  `min_relevance_score = 10`，等于最弱标准的满分，一个 `trending` 关键词即可过闸。
- **跨天去重依赖 Redis**：Redis 不可用时全部放行，跨天重复会重新出现；本仓库不含
  任何去重数据库或历史指纹存档。
- **LLM 判断一致性**：验收器只校验结构、来源与措辞，不能证明结论为真；同一批材料
  两次生成的取舍可能不同，方向、数字仍需对照原文。
- **共享运行时未打包**：`spider_core/` 以仓库内子目录形式被 `sys.path` 导入，没有打包成
  可安装的 pip 包，因此不能作为独立依赖被其他项目复用。`config.json` 不入库，
  `config.example.json` 里的 `vault_path` 是占位符，必须改成自己的 Obsidian vault 路径。
- **Claude CLI 写入受限**：项目位于 CLI 配置目录内时，子进程只能写 `%TEMP%` 暂存区，
  再由 Python 归档验收，因此中间稿不在项目目录。
- **文档口径漂移**：`domains/README.md` 与 `task_registry.json` 仍写「23 源」，与
  `config.json` 实际的 20 个 feed 不一致。

## License

MIT License，见 [LICENSE](LICENSE)。Copyright (c) 2026 dataking5d。

本仓库缺少 `requirements.txt`：依赖需按 `domains/` 下各模块的实际 import 自行安装，这一点尚未补齐。
