# Spider Capability Lifecycle

> 能力从"项目内使用"到"Core 正式模块"的完整生命周期管理。

---

## 1. 生命周期状态

```
                    ┌──────────┐
                    │ candidate │ ← 被识别为通用能力
                    └────┬─────┘
                         │ 用户确认抽离
                    ┌────▼──────┐
                    │experimental│ ← 已抽离，接口可能变化
                    └────┬──────┘
                         │ 2+ 项目稳定使用 30 天以上
                    ┌────▼──────┐
                    │  stable    │ ← 接口稳定，向后兼容
                    └────┬──────┘
                         │ 有更好的替代方案
                    ┌────▼──────┐
                    │ deprecated │ ← 保留 2 个版本周期后移除
                    └───────────┘
```

---

## 2. 状态定义与进出标准

### 2.1 Candidate

**进入条件**（满足任一）：
- 被 2 个以上项目使用相同/几乎相同的代码
- 具有明显的长期通用价值，即使当前只有一个项目使用

**标记方式**：
- 在 registry.json 的 `candidates` 中添加条目
- 在源码中添加注释 `# [Spider Core Candidate]`

**停留时间**：不限，等待用户确认抽离

**退出条件**：
- → experimental: 用户确认抽离，代码进入 core/
- → 删除: 确认不需要抽离（逻辑太薄、语义不通用）

### 2.2 Experimental

**进入条件**：
- 用户已确认抽离
- 代码已放入 core/ 目录
- registry.json 中状态更新为 experimental

**约束**：
- 接口可能变化（不保证向后兼容）
- 必须在至少一个项目中实际使用
- 每次接口变更需在 registry.json 的 notes 中记录

**停留时间**：至少到下一个项目使用它

**退出条件**：
- → stable: 2+ 项目稳定使用 30 天以上，无接口投诉
- → candidate: 接口设计有问题，回到候选重新设计
- → deprecated: 发现根本性缺陷

### 2.3 Stable

**进入条件**（全部满足）：
- 2+ 项目在生产中使用
- 稳定运行 30 天以上
- 接口不再变化
- 有清晰的 docstring / 使用示例

**约束**：
- **向后兼容**：修改不能破坏现有调用方
- 新增参数只能用可选参数（带默认值）
- 破坏性变更需要先创建新模块，旧模块进入 deprecated

**退出条件**：
- → deprecated: 有更好的替代方案，或不再有项目使用

### 2.4 Deprecated

**进入条件**：
- 有更好的替代方案
- 或连续 60 天无项目使用

**约束**：
- 保留至少 2 个版本周期（~60 天）
- import 时打印 warning
- 所有使用方必须迁移后才能删除

**退出条件**：
- → 删除: 所有使用方已迁移，2 个版本周期已过

---

## 3. 抽离决策框架

当发现重复代码时，按以下决策树判断是否抽离：

```
1. 代码是否在 2+ 项目中几乎相同？
   ├─ 否 → 不抽离
   └─ 是 → 继续

2. 抽离后的接口是否清晰（≤3 个参数，单一职责）？
   ├─ 否 → 暂不抽离，记录到 patterns/
   └─ 是 → 继续

3. 逻辑是否 < 20 行且没有复杂依赖？
   ├─ 是 → 可能太薄，评估是否值得一个独立模块
   └─ 否 → 继续

4. 是否与特定项目语义强绑定？
   ├─ 是 → 不抽离（即使代码相同）
   └─ 否 → 标记 Candidate，提出抽离方案
```

### 语义相同 vs 代码相同

代码相同不代表应该抽离。例如：

- `wait_for_network()`: 语义是"等待网络可用" → 通用 → **抽离**
- `validate_output()`: 语义是"检查日报是否符合今日领域格式" → 项目特定 → **不抽离**

---

## 4. registry.json 维护规则

### 4.1 条目格式

```json
{
  "module_name": {
    "status": "candidate|experimental|stable|deprecated",
    "description": "一句话描述",
    "found_in": ["项目A/文件.py", "项目B/文件.py"],
    "signature": "function_name(param) -> return_type",
    "notes": "额外说明"
  }
}
```

### 4.2 更新时机

| 事件 | 更新内容 |
|------|---------|
| 发现新 candidate | 添加条目，status=candidate |
| 开始抽离 | status → experimental，记录抽离日期 |
| 接口变更 | 更新 signature，在 notes 记录变更 |
| 升级为 stable | status → stable，记录确认日期 |
| 弃用 | status → deprecated，添加替代方案链接 |
| 删除 | 从 registry 移除，在 git commit message 中记录 |

### 4.3 一致性检查（手动，每月一次）

```bash
# 检查：registry 中标记的 candidate 是否仍存在
# 检查：registry 中的 signature 是否与实际代码一致
# 检查：stable 模块是否确实被 2+ 项目使用
```

---

## 5. 当前能力状态总览（2026-05-24）

| 能力 | 状态 | 建议动作 |
|------|------|---------|
| logger | candidate | **立即抽离** — 两个项目逐字节相同 |
| network_wait | candidate | **立即抽离** — 两个项目逐字节相同 |
| merge_user_path | candidate | **立即抽离** — 两个项目逐字节相同 |
| read_claudian_config | candidate | 统一接口后抽离 |
| claude_cli_runner | candidate | 待评估 — 先观察第 3 个项目 |
| health_report | candidate → patterns/ | 记录模式，不抽离代码 |
| fallback_generator | candidate → patterns/ | 记录模式，不抽离代码 |
| source_scoring | candidate | 保持 candidate，等待第二个 domain |
| obsidian_writer | candidate | 降级 — 通用部分太薄 |

---

> **维护规则**：本文档在每次能力状态变更后更新。
