"""Exercise both cognition stages with fake CLI/fetch and temporary files only."""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

from test_cognition_quality import load_functions, report

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "spider_core"))
from core.output_utils import archive_agent_draft, resolve_output_path


class NullLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class CognitionPublicationFlowTests(unittest.TestCase):
    def run_flow(self, *, discovery="valid", discovery_exit=0, draft_exit=0,
                 draft_valid=True, unavailable=False):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            vault = base / "vault"
            output = vault / "2026-10-06.md"
            draft_dir = base / "reports/cognition/drafts"
            staging = base / "staging"
            calls, statuses, remembered, health = [], [], [], []

            def fake_cli(args, **kwargs):
                stage = "discovery" if "WebSearch" in args[args.index("--tools") + 1] else "draft"
                calls.append(stage)
                destination = Path(kwargs["input"])
                if stage == "discovery":
                    payloads = {"valid": json.dumps([{"url": "https://example.org/study",
                                 "title": "Study", "domain": "元认知与底层思维"}]),
                                "empty": "[]", "invalid": "not JSON", "invalid_entries": "[{}]"}
                    if discovery != "missing":
                        destination.write_text(payloads[discovery], encoding="utf-8")
                    code = discovery_exit
                else:
                    content = report((0, 0)) if discovery == "empty" else report()
                    destination.write_text(content if draft_valid else "unfinished draft", encoding="utf-8")
                    code = draft_exit
                return SimpleNamespace(returncode=code, stdout="API Error: 402" if code else "", stderr="")

            ns = load_functions(
                argparse=argparse, sys=sys, time=time, datetime=datetime, urlparse=urlparse,
                json=json, subprocess=SimpleNamespace(run=fake_cli,
                    TimeoutExpired=subprocess.TimeoutExpired, CREATE_NO_WINDOW=0),
                PROJECT_ROOT=base, PROJECT_LOGS=base / "logs", OUTPUT_DIR=vault,
                OUTPUT_FILE=output, DRAFT_DIR=draft_dir, VAULT_PATH=vault,
                STATUS_PATH=base / "status.json", TODAY_CN="2026年10月06日",
                ROTATION={"domains": ["元认知与底层思维", "人性洞察与社交逻辑"], "label": "Day 0"},
                CFG={"quality": {"min_total_chars": 2000, "min_chars_per_article": 300,
                                 "min_articles": 4}, "claude": {"effort_level": "high"}},
                slog=NullLogger(), timer=NullLogger(), rw=SimpleNamespace(write=lambda *a, **k: None),
                trend_memory=SimpleNamespace(extract_signals=lambda text: {
                    "keywords": [], "entities": [], "themes": []},
                    update=lambda **kwargs: remembered.append(kwargs), write=lambda: None),
                TopicDedup=lambda *a, **k: SimpleNamespace(save=lambda *a: None))
            ns.update(log=lambda *a: None, validate_system_clock=lambda path: (True, ""),
                      start_http_server=lambda path: None, resolve_output_path=resolve_output_path,
                      wait_for_network=lambda: True, merge_user_path=lambda: None,
                      read_claudian_config=lambda path: ("fake-cli", None), resolve_model=lambda: None,
                      agent_draft_staging_dir=lambda domain: staging,
                      archive_agent_draft=archive_agent_draft,
                      build_discovery_prompt=lambda path: str(path),
                      build_prompt=lambda path, evidence_pack: str(path),
                      write_domain_status=lambda *a, **k: statuses.append(k),
                      write_health=lambda *a: {"grade": "A", "score": 100},
                      print_health=lambda *a: health.append(a),
                      _write_health=lambda *a: health.append(a),
                      update_index=lambda: None,
                      classify_claude_error=lambda *a: ("api_balance", "balance"),
                      dump_claude_io=lambda *a: "mock-io.log", tail=lambda text: text,
                      fetch_page_evidence=lambda url: {
                          "url": url, "final_url": url + "?resolved=1",
                          "status": "unavailable" if unavailable else "excerpt",
                          "text": "" if unavailable else "研究观察到组间差异，不能证明因果。" * 100,
                          "error": "timeout" if unavailable else ""})
            ns["generate_fallback"] = lambda code: None
            exit_code = 0
            with patch.object(sys, "argv", ["curator.py"]):
                try:
                    ns["main"]()
                except SystemExit as exc:
                    exit_code = exc.code
            artifacts = list(draft_dir.glob("*.evidence.json"))
            evidence = json.loads(artifacts[0].read_text(encoding="utf-8")) if artifacts else None
            return {"exit": exit_code, "published": output.exists(), "calls": calls,
                    "statuses": statuses, "remembered": remembered, "evidence": evidence}

    def test_rejected_draft_finishes_without_nameerror(self):
        result = self.run_flow(draft_valid=False)
        self.assertEqual(result["exit"], 1)
        self.assertFalse(result["published"])
        self.assertFalse(result["remembered"])
        self.assertTrue(result["statuses"][-1]["extra"]["degraded"])
        self.assertEqual(result["statuses"][-1]["extra"]["error_kind"], "report_validation")

    def test_failed_draft_cli_finishes_with_classified_failure(self):
        result = self.run_flow(draft_valid=False, draft_exit=1)
        self.assertEqual(result["exit"], 1)
        self.assertEqual(result["statuses"][-1]["extra"]["error_kind"], "api_balance")

    def test_missing_invalid_and_useless_candidates_stop_before_drafting(self):
        for discovery in ("missing", "invalid", "invalid_entries"):
            with self.subTest(discovery=discovery):
                result = self.run_flow(discovery=discovery)
                self.assertEqual(result["exit"], 1)
                self.assertFalse(result["published"])
                self.assertEqual(result["calls"], ["discovery"])
                self.assertTrue(result["statuses"][-1]["extra"]["degraded"])

    def test_failed_discovery_cli_cannot_publish_a_normal_empty_day(self):
        result = self.run_flow(discovery="empty", discovery_exit=1)
        self.assertEqual(result["exit"], 1)
        self.assertFalse(result["published"])
        self.assertEqual(result["calls"], ["discovery"])

    def test_successful_empty_candidate_list_is_an_honest_empty_day(self):
        result = self.run_flow(discovery="empty")
        self.assertEqual(result["exit"], 0)
        self.assertTrue(result["published"])

    def test_complete_candidates_survive_nonzero_cli_exit(self):
        result = self.run_flow(discovery_exit=1)
        self.assertEqual(result["exit"], 0)
        self.assertTrue(result["published"])

    def test_unavailable_source_cannot_publish_as_abstract(self):
        result = self.run_flow(unavailable=True)
        self.assertEqual(result["exit"], 1)
        self.assertFalse(result["published"])
        self.assertFalse(result["remembered"])
        self.assertEqual(result["evidence"]["sources"][0]["status"], "unavailable")
        self.assertEqual(result["evidence"]["sources"][0]["error"], "timeout")

    def test_success_archives_evidence_and_counts_articles(self):
        result = self.run_flow()
        self.assertEqual(result["exit"], 0)
        self.assertTrue(result["published"])
        self.assertEqual(result["statuses"][-1]["total_items"], 4)
        self.assertEqual(result["evidence"]["date"], "2026-10-06")
        entry = result["evidence"]["sources"][0]
        self.assertEqual(entry["url"], "https://example.org/study")
        self.assertTrue(entry["final_url"].endswith("?resolved=1"))
        self.assertEqual(entry["status"], "excerpt")
        self.assertTrue(entry["text"])
        self.assertTrue(entry["fetched_at"])
        self.assertTrue(any(s.get("progress") == {"done": 1, "total": 1}
                            for s in result["statuses"]))


if __name__ == "__main__":
    unittest.main()
