"""Offline regression tests: extract functions without importing the pipeline."""
import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "spider_core"))
from core.evidence import STATUS_EXCERPT, normalize_url  # noqa: E402


def load_functions(**overrides):
    tree = ast.parse((ROOT / "domains/cognition/curator.py").read_text(encoding="utf-8"))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    # validate_output() matches source URLs with the module's own pattern; take
    # that assignment rather than restating the regex here, so a change to it
    # cannot pass unnoticed.
    functions += [n for n in tree.body
                  if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "SOURCE_URL_RE"
                          for t in n.targets)]
    context = {
        "re": re, "Path": Path, "TODAY": "2026-10-06", "ROTATION_DAY": 0,
        "ROTATION": {"domains": ["元认知与底层思维", "人性洞察与社交逻辑"]},
        "CFG": {"quality": {"min_total_chars": 2000, "min_chars_per_article": 300,
                            "min_articles": 4, "min_a_grade_sources": 2}},
        "print": lambda *a, **kw: None,
        "normalize_url": normalize_url, "STATUS_EXCERPT": STATUS_EXCERPT,
    }
    context.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), "curator-functions", "exec"), context)
    return context


def report(counts=(2, 2), missing=True, links=True):
    text = """---
date: 2026-10-06
tags:
  - 每日认知
curation_quality: C
domains:
  - 元认知与底层思维
  - 人性洞察与社交逻辑
rotation: 0/3
---
# 每日认知精选
"""
    for number, (domain, count) in enumerate(zip(("元认知与底层思维", "人性洞察与社交逻辑"), counts)):
        text += f"\n## {'🔍' if number == 0 else '🫂'} {domain}\n"
        for number in range(count):
            source = "[研究原文](https://example.org/study)" if links else "期刊 2026 年论文"
            text += f"\n### 📄 发现 {number}\n**来源**：{source}\n**已读材料**：摘要\n"
            text += "**核心发现**：" + "研究在指定实验条件下发现组间存在差异，结果依赖任务类型，不能理解为对所有人的保证。" * 10 + "\n"
            text += "**适用边界**：" + "这里只测量实验任务中的行为，不能证明日常生活里的因果关系。" * 4 + "\n"
            text += "**我的建议**：记录自己的体验作为小实验；这项建议并不是论文验证过的干预。\n"
        if count < 2 and missing:
            text += "\n今日该领域暂无符合标准的新内容（其余候选未取得足够证据，保留以上已核实条目）。\n"
    text += "\n## 📋 今日行动\n今日无额外行动建议。\n\n[[每日认知精选索引]]\n"
    return text


class CognitionQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "2026-10-06.md"
        self.ctx = load_functions(OUTPUT_FILE=self.path)

    def check(self, content):
        self.path.write_text(content, encoding="utf-8")
        return self.ctx["validate_output"]()[0]

    def test_two_headings_do_not_cancel_errors(self):
        self.assertFalse(self.check("### 📄 A\n### 📄 B\n" + "x" * 600))

    def test_full_report_passes(self):
        self.assertTrue(self.check(report()))

    def test_wrong_date_rejected(self):
        self.assertFalse(self.check(report().replace("date: 2026-10-06", "date: 1999-01-01")))

    def test_unclosed_frontmatter_rejected(self):
        self.assertFalse(self.check(report().replace("rotation: 0/3\n---", "rotation: 0/3")))

    def test_yaml_domain_cannot_substitute_for_section(self):
        self.assertFalse(self.check(report().replace("## 🫂 人性洞察与社交逻辑", "## 无关领域")))

    def test_each_article_needs_source_link(self):
        self.assertFalse(self.check(report(links=False)))

    def test_short_actual_body_rejected(self):
        content = re.sub(r"\*\*核心发现\*\*：[^\n]+", "**核心发现**：很有用。", report())
        self.assertFalse(self.check(content))

    def test_explicit_partial_day_allowed(self):
        self.assertTrue(self.check(report((1, 0))))

    def test_explicit_empty_day_allowed(self):
        self.assertTrue(self.check(report((0, 0))))

    def test_silent_missing_articles_rejected(self):
        self.assertFalse(self.check(report((1, 0), missing=False)))

    def test_old_complete_report_is_preserved_for_review(self):
        self.path.write_text(report(links=False), encoding="utf-8")
        self.assertTrue(self.ctx["validate_output"](self.path, legacy=True)[0])
        self.assertFalse(self.ctx["validate_output"](self.path)[0])

    def test_valid_numbered_report_prevents_regeneration(self):
        self.path.write_text("broken", encoding="utf-8")
        completed = self.path.with_name("2026-10-06（1）.md")
        completed.write_text(report(), encoding="utf-8")
        found, issues = self.ctx["find_existing_report"](self.path)
        self.assertEqual(found, completed)
        self.assertEqual(issues, [])

    def test_old_incomplete_report_is_not_success(self):
        self.path.write_text("### 📄 A\n### 📄 B\n" + "x" * 3000, encoding="utf-8")
        self.assertIsNone(self.ctx["find_existing_report"](self.path)[0])

    def test_build_prompt_call_supplies_the_draft_path(self):
        """Guards the signature/call mismatch that aborted every run: main()
        called build_prompt() while the function required a draft path."""
        tree = ast.parse((ROOT / "domains/cognition/curator.py").read_text(encoding="utf-8"))
        signatures = {n.name: len(n.args.args)
                      for n in tree.body if isinstance(n, ast.FunctionDef)}
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "build_prompt"]
        self.assertTrue(calls, "build_prompt is never called")
        for call in calls:
            self.assertEqual(len(call.args) + len(call.keywords),
                             signatures["build_prompt"])

    def test_publish_gate_rejects_a_stub_and_leaves_the_vault_untouched(self):
        draft = Path(self.tmp.name) / "draft.md"
        draft.write_text("### 📄 A\n### 📄 B\n" + "x" * 600, encoding="utf-8")
        vault = Path(self.tmp.name) / "vault.md"
        self.assertTrue(self.ctx["publish_draft"](draft, vault))
        self.assertFalse(vault.exists())
        self.assertTrue(draft.exists(), "a rejected draft must stay for diagnosis")

    def test_publish_gate_copies_a_valid_draft(self):
        draft = Path(self.tmp.name) / "draft.md"
        draft.write_text(report(), encoding="utf-8")
        vault = Path(self.tmp.name) / "vault.md"
        self.assertEqual(self.ctx["publish_draft"](draft, vault), [])
        self.assertEqual(vault.read_text(encoding="utf-8"), report())

    def test_publish_gate_never_clobbers_an_existing_note(self):
        draft = Path(self.tmp.name) / "draft.md"
        draft.write_text(report(), encoding="utf-8")
        vault = Path(self.tmp.name) / "vault.md"
        vault.write_text("historical note", encoding="utf-8")
        self.assertTrue(self.ctx["publish_draft"](draft, vault))
        self.assertEqual(vault.read_text(encoding="utf-8"), "historical note")

    def test_missing_draft_is_not_a_publish(self):
        vault = Path(self.tmp.name) / "vault.md"
        self.assertTrue(self.ctx["publish_draft"](
            Path(self.tmp.name) / "absent.md", vault))
        self.assertFalse(vault.exists())

    def test_fallback_never_writes_into_the_vault(self):
        """A placeholder carrying an error code must not become a note."""
        tree = ast.parse((ROOT / "domains/cognition/curator.py").read_text(encoding="utf-8"))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "generate_fallback")
        used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        self.assertNotIn("OUTPUT_FILE", used)
        self.assertNotIn("OUTPUT_DIR", used)

    def assembled_prompt(self):
        ctx = load_functions(
            PROMPT_TEMPLATE_PATH=ROOT / "domains/cognition/prompt_template.md",
            PROJECT_ROOT=ROOT,
            QUALITY_FILE=Path(self.tmp.name) / "absent-quality.md",
            INDEX_FILE=Path(self.tmp.name) / "absent-index.md",
            ROTATION={"label": "元认知 + 人性洞察",
                      "domains": ["元认知与底层思维", "人性洞察与社交逻辑"],
                      "domain_emojis": ["🔍", "🫂"],
                      "search_topics_cn": ["元认知"], "search_topics_en": ["metacognition"],
                      "preferred_sources": ["Nature"]},
            CFG={"quality": {"max_recent_issues_for_fewshot": 0, "max_fewshot_chars_per_issue": 0},
                 "rotation": {"cycle": [{"domains": ["a", "b"]}, {"domains": ["c", "d"]},
                                        {"domains": ["e", "f"]}]}},
            TODAY_CN="2026年10月06日",
            trend_memory=None,
        )
        ctx["load_recent_issues"] = lambda **kwargs: ""
        ctx["_build_cognition_seen_before"] = lambda tm: ""
        draft = Path(self.tmp.name) / "drafts" / "2026-10-06-1.md"
        return ctx["build_prompt"](draft), draft

    def test_assembled_prompt_points_at_the_draft_and_the_required_fields(self):
        prompt, draft = self.assembled_prompt()
        self.assertIn(str(draft), prompt)
        for field in ("**来源**", "**已读材料**", "**核心发现**", "**适用边界**", "**我的建议**"):
            self.assertIn(field, prompt)
        self.assertIn("暂无符合标准的新内容", prompt)
        self.assertIn("QUALITY_RULES.md", prompt)

    def test_template_no_longer_asks_for_sections_the_validator_rejects(self):
        """The old template demanded 为什么重要 / 可落地 and no link, so every
        draft was rejected once the validator started requiring the new fields."""
        prompt, _ = self.assembled_prompt()
        for stale in ("**为什么重要**", "**可落地**"):
            self.assertNotIn(stale, prompt)

    def test_parse_daily_articles_reads_a_numbered_repaired_report(self):
        """A repaired day lives at "…（1）.md" while OUTPUT_FILE holds the
        rejected original — reading the wrong one raised FileNotFoundError."""
        numbered = Path(self.tmp.name) / "2026-10-06（1）.md"
        numbered.write_text(report(), encoding="utf-8")
        articles = self.ctx["parse_daily_articles"](numbered)
        self.assertEqual({k: len(v) for k, v in articles.items()},
                         {"元认知与底层思维": 2, "人性洞察与社交逻辑": 2})

    def test_parse_daily_articles_falls_back_to_output_file(self):
        self.path.write_text(report(), encoding="utf-8")
        self.assertEqual(sum(len(v) for v in self.ctx["parse_daily_articles"]().values()), 4)

    def test_repaired_report_replaces_stale_index_links_and_summaries(self):
        numbered = self.path.with_name("2026-10-06（1）.md")
        numbered.write_text(report(), encoding="utf-8")
        index = Path(self.tmp.name) / "index.md"
        index.write_text("""# 索引
## 三、按日期索引
### 2026年10月
- [[2026-10-06]] — 旧残稿

## 四、按领域索引
### 🔍 元认知与底层思维
| 日期 | 核心 |
| --- | --- |
| [[2026-10-06]] | 旧残稿 |
### 🫂 人性洞察与社交逻辑
| 日期 | 核心 |
| --- | --- |
| [[2026-10-06]] | 旧残稿 |
""", encoding="utf-8")
        self.ctx.update(OUTPUT_FILE=numbered, INDEX_FILE=index)
        self.assertTrue(self.ctx["update_index"]())
        content = index.read_text(encoding="utf-8")
        self.assertNotIn("[[2026-10-06]]", content)
        self.assertNotIn("旧残稿", content)
        self.assertEqual(content.count("[[2026-10-06（1）]]"), 3)


if __name__ == "__main__":
    unittest.main()
