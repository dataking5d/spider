"""The cognition domain reads sources with Python, and must say so honestly.

Regression guard for the 2026-10-07 finding: the child CLI's WebFetch tool
cannot pass its per-domain safety check against this machine's non-Anthropic API
relay, so every source came back "unable to verify" and the domain published
empty reports for days while looking healthy. Fetching moved to Python
(core.evidence); these tests lock the two halves — that Python really fetches,
and that the draft may not claim more than Python obtained.
"""
import ast
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CURATOR = ROOT / "domains/cognition/curator.py"
sys.path.insert(0, str(ROOT / "spider_core"))

from core.evidence import (STATUS_EXCERPT, STATUS_UNAVAILABLE,  # noqa: E402
                           fetch_page_evidence, normalize_url)


def _extract(names):
    """Exec the named module-level functions and the SOURCE_URL_RE assignment.

    The pipeline is a script with import-time side effects (it reads config,
    creates directories, opens trend memory), so — as elsewhere in this suite —
    the functions are lifted out of the AST rather than imported.
    """
    tree = ast.parse(CURATOR.read_text(encoding="utf-8"))
    body = [node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in names]
    body += [node for node in tree.body
             if isinstance(node, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "SOURCE_URL_RE"
                     for t in node.targets)]
    context = {
        "re": re, "Path": Path, "json": json, "print": lambda *a, **kw: None,
        "log": lambda *a, **kw: None,
        "TODAY": "2026-10-06", "TODAY_CN": "2026年10月06日", "ROTATION_DAY": 0,
        "ROTATION": {"domains": ["元认知与底层思维", "人性洞察与社交逻辑"],
                     "domain_emojis": ["🔍", "🫂"],
                     "search_topics_cn": ["元认知"], "search_topics_en": ["metacognition"],
                     "preferred_sources": ["Nature"], "label": "认知"},
        "CFG": {"quality": {"min_total_chars": 200, "min_chars_per_article": 50,
                            "min_articles": 4},
                "source_reachability": {
                    "readable": {"academic_open": ["pmc.ncbi.nlm.nih.gov"],
                                 "note": "NBER 的 PDF 直链可读"},
                    "not_readable": {"bot_wall_403": ["sciencedirect.com"]}}},
        "normalize_url": normalize_url, "STATUS_EXCERPT": STATUS_EXCERPT,
        "fetch_page_evidence": fetch_page_evidence, "urlparse": urlparse,
        "datetime": datetime, "STATUS_PATH": Path("unused-status.json"),
        "write_domain_status": lambda *a, **kw: None,
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), "curator-functions", "exec"), context)
    return context


def report(url="https://example.org/a", read_material="原文摘录"):
    """A structurally valid four-article report."""
    prose = "研究在指定实验条件下观察到组间差异，效应依赖任务类型与测量方式。" * 5
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
# 🧠 每日认知精选 | 2026年10月06日
"""
    for emoji, domain in (("🔍", "元认知与底层思维"), ("🫂", "人性洞察与社交逻辑")):
        text += f"\n## {emoji} {domain}\n"
        for number in range(2):
            text += (f"\n### 📄 发现 {number}\n"
                     f"**来源**：[研究原文]({url})｜期刊 (2026)\n"
                     f"**已读材料**：{read_material}\n"
                     f"**核心发现**：{prose}\n"
                     f"**适用边界**：{prose}\n"
                     f"**我的建议**：{prose}\n")
    text += "\n## 📋 今日行动\n- [ ] 试着记录一次自己的判断依据\n\n[[每日认知精选索引]]\n"
    return text


class EvidenceFetchTests(unittest.TestCase):
    def test_unreachable_source_is_recorded_not_raised(self):
        """One dead source must not take down an unattended daily run."""
        result = fetch_page_evidence("http://127.0.0.1:1/nothing-here")
        self.assertEqual(result["status"], STATUS_UNAVAILABLE)
        self.assertTrue(result["error"])
        self.assertEqual(result["text"], "")

    def test_non_http_url_is_refused_without_a_request(self):
        result = fetch_page_evidence("ftp://example.org/file")
        self.assertEqual(result["status"], STATUS_UNAVAILABLE)
        self.assertIn("http", result["error"])

    def test_normalize_ignores_case_and_trailing_slash(self):
        self.assertEqual(normalize_url("https://Example.ORG/a/"),
                         normalize_url("https://example.org/a"))
        self.assertNotEqual(normalize_url("https://example.org/a?x=1"),
                            normalize_url("https://example.org/a"))

    def test_candidate_list_is_filtered_and_deduplicated(self):
        context = _extract({"parse_candidates"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.json"
            path.write_text(json.dumps([
                {"url": "https://example.org/a", "title": "A"},
                {"url": "https://example.org/a/", "title": "A duplicate"},
                {"url": "not-a-url", "title": "B"},
                "not even an object",
                {"title": "no url at all"},
            ]), encoding="utf-8")
            candidates = context["parse_candidates"](path)
        self.assertEqual([c["title"] for c in candidates], ["A"])

    def test_missing_candidate_list_is_a_discovery_failure(self):
        context = _extract({"parse_candidates"})
        with self.assertRaises(ValueError):
            context["parse_candidates"](Path("does/not/exist.json"))

    def test_fetch_is_bounded(self):
        """A runaway candidate list must not become an hours-long fetch loop."""
        context = _extract({"fetch_candidate_evidence"})
        calls = []
        context["fetch_page_evidence"] = lambda url: calls.append(url) or {
            "url": url, "status": STATUS_UNAVAILABLE, "text": "", "error": "stub"}
        candidates = [{"url": f"https://example.org/{n}"} for n in range(50)]
        pack = context["fetch_candidate_evidence"](candidates, limit=3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(pack), 3)


class EvidenceIsReportedHonestlyTests(unittest.TestCase):
    def test_unavailable_candidate_is_shown_as_unusable(self):
        context = _extract({"render_evidence_pack"})
        rendered = context["render_evidence_pack"]([
            {"url": "https://example.org/a", "status": STATUS_EXCERPT, "text": "正文"},
            {"url": "https://example.org/b", "status": STATUS_UNAVAILABLE,
             "text": "", "error": "ConnectionError: refused"},
        ])
        self.assertIn("已取得正文摘录", rendered)
        self.assertIn("未能取得", rendered)
        self.assertIn("ConnectionError", rendered)
        self.assertIn("不得", rendered)


class DraftMayNotOutrunTheEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.context = _extract({"validate_output"})

    def validate(self, text, evidence):
        path = Path(self.tmp.name) / "draft.md"
        path.write_text(text, encoding="utf-8")
        return self.context["validate_output"](path, evidence=evidence)[1]

    def test_clean_draft_passes(self):
        evidence = {normalize_url("https://example.org/a"): STATUS_EXCERPT}
        self.assertEqual(self.validate(report(), evidence), [])

    def test_citing_a_source_never_retrieved_is_rejected(self):
        """The whole point of the change: a plausible URL is not evidence."""
        evidence = {normalize_url("https://example.org/other"): STATUS_EXCERPT}
        errors = self.validate(report(), evidence)
        self.assertTrue(any("never retrieved" in e for e in errors), errors)

    def test_claiming_the_text_when_the_page_failed_is_rejected(self):
        evidence = {normalize_url("https://example.org/a"): STATUS_UNAVAILABLE}
        errors = self.validate(report(read_material="原文摘录"), evidence)
        self.assertTrue(any("could not be read" in e for e in errors), errors)

    def test_summary_only_claim_on_a_failed_page_is_rejected(self):
        """A failed fetch provides no abstract either: it cannot support a card."""
        evidence = {normalize_url("https://example.org/a"): STATUS_UNAVAILABLE}
        self.assertTrue(self.validate(report(read_material="仅摘要"), evidence))

    def test_excerpt_cannot_be_called_full_text(self):
        evidence = {normalize_url("https://example.org/a"): STATUS_EXCERPT}
        self.assertTrue(self.validate(report(read_material="全文"), evidence))

    def test_explicitly_unread_full_text_is_not_a_full_text_claim(self):
        evidence = {normalize_url("https://example.org/a"): STATUS_EXCERPT}
        for material in ("原文摘录（未读全文）", "仅摘要（未读论文全文）",
                         "原文摘录（没有阅读全文）", "原文摘录（全文未读）"):
            with self.subTest(material=material):
                self.assertEqual(self.validate(report(read_material=material), evidence), [])

    def test_a_positive_claim_after_a_denial_remains_rejected(self):
        evidence = {normalize_url("https://example.org/a"): STATUS_EXCERPT}
        errors = self.validate(report(read_material="未读论文全文，但已阅读全文"), evidence)
        self.assertTrue(any("full-text access" in error for error in errors), errors)

    def test_evidence_records_are_accepted_without_claiming_full_text(self):
        evidence = {normalize_url("https://example.org/a"): {
            "status": STATUS_EXCERPT, "text": "研究观察到组间差异。" * 100}}
        self.assertEqual(self.validate(report(), evidence), [])

    def test_history_is_still_validated_on_structure_alone(self):
        """Existing notes predate the evidence index and must stay readable."""
        path = Path(self.tmp.name) / "old.md"
        path.write_text(report(), encoding="utf-8")
        self.assertEqual(self.context["validate_output"](path)[1], [])


class PromptShapeTests(unittest.TestCase):
    def test_drafting_prompt_carries_the_evidence_and_asks_for_no_search(self):
        source = CURATOR.read_text(encoding="utf-8")
        tree = ast.parse(source)
        build_prompt = next(node for node in tree.body
                            if isinstance(node, ast.FunctionDef) and node.name == "build_prompt")
        body = ast.get_source_segment(source, build_prompt)
        self.assertIn("render_evidence_pack(evidence_pack)", body,
                      "the drafting prompt no longer carries the fetched evidence")
        self.assertNotIn("web_search", body,
                         "the drafting prompt still tells the model to search — "
                         "searching happens in stage 1")
        self.assertIn("只允许引用上面出现过的链接", body)

    def test_discovery_prompt_asks_only_for_candidates(self):
        context = _extract({"build_discovery_prompt", "render_source_reachability"})
        prompt = context["build_discovery_prompt"](Path("out.json"))
        self.assertIn("web_search", prompt)
        self.assertIn("只检索，不写稿", prompt)
        self.assertIn("out.json", prompt)

    def test_discovery_prompt_names_the_sources_this_machine_can_read(self):
        """Regression guard for the 2026-10-07 starvation.

        Stage 1 was told only the paywalled journals in `rotation.preferred_sources`
        and returned candidates from exactly those hosts; the program then read 0
        of 14. Naming the journals is right — naming only them is the bug. So the
        prompt must carry the measured reachability table alongside them.
        """
        context = _extract({"build_discovery_prompt", "render_source_reachability"})
        prompt = context["build_discovery_prompt"](Path("out.json"))
        self.assertIn("pmc.ncbi.nlm.nih.gov", prompt)
        self.assertIn("sciencedirect.com", prompt)
        self.assertIn("优先从这里挑", prompt)

    def test_a_missing_reachability_table_does_not_break_the_prompt(self):
        """The table is a measurement and may be absent; the pipeline still runs."""
        context = _extract({"build_discovery_prompt", "render_source_reachability"})
        context["CFG"] = {}
        self.assertEqual(context["render_source_reachability"](), "")
        self.assertIn("web_search", context["build_discovery_prompt"](Path("out.json")))

    def test_fetch_failures_are_named_individually(self):
        """`0/14` alone cannot say 403-wall vs TLS vs too-big — three different fixes."""
        context = _extract({"summarize_fetch_failures"})
        summary = context["summarize_fetch_failures"]([
            {"url": "https://example.org/ok", "status": STATUS_EXCERPT, "error": ""},
            {"url": "https://sciencedirect.com/a", "status": STATUS_UNAVAILABLE,
             "error": "HTTPError: 403 Client Error"},
        ])
        self.assertIn("sciencedirect.com", summary)
        self.assertIn("403", summary)
        self.assertNotIn("example.org", summary)


if __name__ == "__main__":
    unittest.main()
