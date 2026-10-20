"""Offline regressions: never import or execute the fetch/report entrypoints."""

import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parents[1]


def load_module(path):
    namespace = {"__file__": str(path), "__name__": "offline_test"}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


ENGINE = load_module(ROOT / "spider_core/scoring/engine.py")
MERGER = load_module(ROOT / "domains/ai/event_merger.py")
FETCH_TREE = ast.parse((ROOT / "fetch_ai_news.py").read_text(encoding="utf-8"))
FETCH = dict(re=re, json=json, hashlib=hashlib, Path=Path, datetime=datetime,
             timedelta=timedelta, timezone=timezone, urljoin=urljoin,
             MAX_CHARS=800, TIMEOUT=20, HEADERS={}, BASE_DIR=ROOT)
exec(compile(ast.Module(body=[n for n in FETCH_TREE.body
                             if isinstance(n, ast.FunctionDef)], type_ignores=[]),
             "fetch_ai_news.py", "exec"), FETCH)
FETCH.update({k: v for k, v in MERGER.items() if not k.startswith("__")})
CFG = json.loads((ROOT / "domains/ai/scoring_config.json").read_text(encoding="utf-8"))
CFG["min_relevance_score"] = 15
for node in FETCH_TREE.body:
    if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "AI_CONTEXT_TERMS" for t in node.targets):
        CFG["dimensions"]["relevance"]["context_terms"] = ast.literal_eval(node.value)


def saved(date, title_prefix):
    data = json.loads((ROOT / f"data/ai_news_raw_{date}.json").read_text(encoding="utf-8"))
    return next(copy.deepcopy(item) for item in data["items"]
                if item["title"].startswith(title_prefix))


class AcquisitionQualityTests(unittest.TestCase):
    def test_github_observation_is_not_publication(self):
        anchor = SimpleNamespace(get=lambda key, default="": "/owner/ai-agent")
        desc = SimpleNamespace(text="An open source AI agent")
        repo = SimpleNamespace(select_one=lambda selector: {
            "h2 a": anchor, "p.col-9": desc}.get(selector))
        response = SimpleNamespace(text="fixture", raise_for_status=lambda: None)
        FETCH["requests"] = SimpleNamespace(get=lambda *a, **k: response)
        FETCH["BeautifulSoup"] = lambda *a, **k: SimpleNamespace(select=lambda _: [repo])
        item = FETCH["fetch_github_trending"](
            {"name": "GitHub Trending Python", "url": "https://github.com/trending"}, 70)[0]
        self.assertFalse(item["published"])
        self.assertTrue(item["observed_at"])
        ENGINE["score_items"]([item], CFG)
        self.assertEqual(item["_scores"].get("freshness", 0), 0)
        self.assertNotIn("刚刚发布", item["_reasons"])

    def test_shared_vendor_and_agent_do_not_merge_distinct_events(self):
        pair = [saved("2026-09-29", "Ringg"), saved("2026-09-29", "NVIDIA shipped")]
        FETCH["cluster_by_entities"](pair, CFG["entity_clusters"])
        result = MERGER["merge_events"](pair)
        self.assertEqual(len(result["enhanced_items"]), 2)
        self.assertTrue(all(not item["_cluster_multi_source"] for item in pair))

    def test_legacy_cluster_is_rechecked_before_merging(self):
        pair = [saved("2026-09-29", "Ringg"), saved("2026-09-29", "NVIDIA shipped")]
        self.assertEqual(len(MERGER["merge_events"](pair)["enhanced_items"]), 2)

    def test_split_legacy_cluster_loses_false_verification_claim(self):
        pair = [saved("2026-09-29", "Ringg"), saved("2026-09-29", "NVIDIA shipped")]
        for item in pair:
            item["_reasons"].append("多源验证")
        result = MERGER["merge_events"](pair)["enhanced_items"]
        self.assertTrue(all("多源验证" not in item["_reasons"] for item in result))

    def test_true_duplicate_preserves_each_source_evidence(self):
        a = saved("2026-09-29", "Ringg")
        b = dict(a, source_name="Independent source", link="https://example.org/ringg",
                 description="A separately sourced report with its original evidence.")
        pair = [a, b]
        FETCH["cluster_by_entities"](pair, CFG["entity_clusters"])
        result = MERGER["merge_events"](pair)["enhanced_items"]
        self.assertEqual(len(result), 1)
        self.assertEqual({e["link"] for e in result[0]["_merged_evidence"]},
                         {a["link"], b["link"]})
        self.assertEqual(result[0]["_merged_evidence"][1]["description"], b["description"])

    def test_title_dedup_also_preserves_evidence(self):
        a = saved("2026-09-29", "Ringg")
        b = dict(a, source_name="Independent source", link="https://example.org/ringg")
        result = ENGINE["deduplicate"]([a, b])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["_merged_evidence"]), 2)

    def test_url_and_generic_words_do_not_admit_non_ai_news(self):
        cases = [("2026-09-30", "U.S. postal"), ("2026-09-30", "比预售"),
                 ("2026-10-03", "Apple confirms"), ("2026-10-04", "Surely you have")]
        for date, title in cases:
            with self.subTest(title=title):
                self.assertEqual(ENGINE["score_items"]([saved(date, title)], CFG), [])

    def test_ai_context_does_not_turn_word_fragments_into_score_reasons(self):
        config = copy.deepcopy(CFG)
        config.update(min_relevance_score=0, min_total_score=0)
        for title in ("AI network outage", "AI photograph gallery",
                      "AI coverage roundup", "AI Scottish accents"):
            with self.subTest(title=title):
                item = {"title": title, "description": ""}
                ENGINE["score_items"]([item], config)
                self.assertEqual(item["_matched_criteria"], [])
                self.assertEqual(item["_scores"]["long_term_value"], 0)

    def test_keyword_matching_preserves_regular_forms_and_chinese(self):
        pairs = [("AI workflows", "workflow"), ("Claude skills", "skill"),
                 ("open-source AI", "open source"), ("computer-use agents", "computer use"),
                 ("AI agents", "agent"), ("agentic AI", "agent"),
                 ("Qwen3.8", "qwen"), ("GPT6", "gpt"),
                 ("pathology foundation models", "foundation model"),
                 ("fine-tuning", "fine-tun"), ("fine-tuned", "fine-tun"),
                 ("全自动化工作流", "自动化")]
        for text, term in pairs:
            with self.subTest(text=text, term=term):
                self.assertTrue(ENGINE["_contains_term"](text.lower(), term))

    def test_regular_forms_still_reach_the_scoring_gate(self):
        pairs = [("AI workflows", "workflow_change"), ("Claude skills", "career_impact"),
                 ("open-source AI", "lower_barrier")]
        for title, criterion in pairs:
            with self.subTest(title=title):
                result = ENGINE["score_items"]([{"title": title, "description": ""}], CFG)
                self.assertEqual(len(result), 1)
                self.assertIn(criterion, result[0]["_matched_criteria"])

    def test_real_ai_reports_keep_relevance(self):
        cases = [("2026-09-29", "Ringg"), ("2026-09-30", "Introducing GPT"),
                 ("2026-10-04", "Tracer-Cloud"), ("2026-10-01", "Manus 2.0"),
                 ("2026-10-01", "Composio"), ("2026-10-03", "A model guide"),
                 ("2026-10-03", "Qwen3.8"), ("2026-09-30", "Show HN:"),
                 ("2026-09-28", "GigaPath"), ("2026-10-03", "Chatham"),
                 ("2026-10-03", "Show HN: Made an open-source")]
        for date, title in cases:
            with self.subTest(title=title):
                self.assertEqual(len(ENGINE["score_items"]([saved(date, title)], CFG)), 1)

    def test_generic_scoring_config_does_not_gain_ai_restriction(self):
        config = {"min_relevance_score": 1, "dimensions": {"relevance": {
            "keywords": {"education": {"score": 2, "terms": ["school"]}}}}}
        self.assertEqual(len(ENGINE["score_items"](
            [{"title": "New school opens", "description": ""}], config)), 1)

    def test_new_agent_events_are_not_halved_by_english_bigram_overlap(self):
        pair = [saved("2026-09-29", "Ringg"), saved("2026-09-29", "NVIDIA shipped")]
        expected = {item["link"]: item["_total_score"]
                    for item in ENGINE["score_items"](copy.deepcopy(pair), CFG)}

        class MisleadingTopicHistory:
            def __init__(self, *args, **kwargs):
                pass

            def load_recent(self, **kwargs):
                return 100

            def fingerprint_items(self, items):
                for item in items:
                    item["_total_score"] *= 0.5
                return items, len(items)

        FETCH.update({name: ENGINE[name] for name in (
            "score_items", "deduplicate", "apply_multi_source_boost", "filter_low_quality")})
        FETCH.update(SCORING_CFG=CFG, TopicDedup=MisleadingTopicHistory, log=lambda *a: None)
        result, stats = FETCH["run_scoring_pipeline"](pair)
        self.assertEqual(stats["topic_dedup_downgraded"], 0)
        self.assertEqual({item["link"]: item["_total_score"] for item in result}, expected)

    def test_published_history_only_suppresses_unchanged_published_item(self):
        item = saved("2026-10-04", "Tracer-Cloud")
        history = [dict(item, published_on="2026-10-03")]
        untouched = dict(item, link="https://example.org/unpublished")
        changed = dict(item, description=item["description"] + " New Windows support.")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "published_sources.json"
            path.write_text(json.dumps(history), encoding="utf-8")
            result, count = FETCH["filter_published_items"](
                [item, untouched, changed], path, today="2026-10-04")
        self.assertEqual(count, 1)
        self.assertEqual(result, [untouched, changed])

    def test_star_count_change_is_not_a_new_release(self):
        item = {"link": "https://github.com/a/b", "title": "a/b",
                "description": "[GitHub Stars: 100] An AI agent"}
        history = [dict(item, published_on="2026-10-03")]
        changed_stars = dict(item, description="[GitHub Stars: 120] An AI agent")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "published_sources.json"
            path.write_text(json.dumps(history), encoding="utf-8")
            result, count = FETCH["filter_published_items"](
                [changed_stars], path, today="2026-10-04")
        self.assertEqual((result, count), ([], 1))

    def test_absent_or_expired_history_keeps_candidates(self):
        item = saved("2026-10-04", "Tracer-Cloud")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "published_sources.json"
            self.assertEqual(FETCH["filter_published_items"](
                [item], path, today="2026-10-04"), ([item], 0))
            path.write_text(json.dumps([dict(item, published_on="2026-09-01")]), encoding="utf-8")
            self.assertEqual(FETCH["filter_published_items"](
                [item], path, today="2026-10-04"), ([item], 0))


if __name__ == "__main__":
    unittest.main()
