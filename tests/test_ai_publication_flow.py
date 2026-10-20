"""Run the orchestrator with fake fetch/CLI in a temporary workspace only."""
import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'spider_core'))
from core.output_utils import agent_draft_staging_dir, archive_agent_draft
from domains.claim_checks import validate_claim_wording


class NullLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class PublicationFlowTests(unittest.TestCase):
    def run_pipeline(self, complete, cli_exit, previous_broken=False, secondary_source=False):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base/'data').mkdir()
            for name in ('prompt_template.md', 'QUALITY_RULES.md'):
                (base/name).write_text('test rules', encoding='utf-8')
            item = {'title': 'Agent release', 'link': 'https://example.org/release',
                    'description': 'Public AI agent announcement', '_total_score': 80}
            input_items = [item]
            if secondary_source:
                item.update(title='A confirmed same-event agent announcement',
                            source_name='First source', _cluster_id=1)
                input_items.append({**item, 'link': 'https://example.org/secondary',
                                    'source_name': 'Second source', '_total_score': 70})
            data_file = base/'data/input.json'
            data_file.write_text(json.dumps({'items': input_items, 'total_items_after_filter': len(input_items),
                                            'source_health': []}), encoding='utf-8')
            final = base/'vault/2026-10-06_AI情报.md'
            if previous_broken:
                final.parent.mkdir()
                final.write_text('# Previous incomplete report', encoding='utf-8')
            expected = final.with_name(final.stem + '（1）.md') if previous_broken else final
            local = base/'reports/ai/2026-10-06-ai.md'
            updates = []
            calls = []
            def output_path(path):
                number, candidate = 0, path
                while candidate.exists():
                    number += 1
                    candidate = path.with_name(f'{path.stem}（{number}）{path.suffix}')
                return candidate
            def archive(content, **kwargs):
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_text(content, encoding='utf-8')
            def fake_cli(command, **kwargs):
                calls.append(command)
                if command[0] != 'fake-claude':
                    return SimpleNamespace(returncode=0, stderr='')
                prompt = kwargs['input']
                self.assertEqual(kwargs['cwd'], str(base))
                path = Path(re.search(r'Write only the complete Markdown draft to (.+?)\. Do not publish', prompt)[1])
                # The child CLI cannot write anywhere under CLAUDE_CONFIG_DIR,
                # and this project lives inside that tree. Naming an in-project
                # path here is what made both domains fail with "Draft file not
                # found" on 2026-10-06 — the prompt must point outside it.
                self.assertFalse(path.is_relative_to(base),
                                 'the prompt tells the CLI to write inside the project')
                self.assertEqual(path.parent, agent_draft_staging_dir('ai'))
                if complete:
                    content = ('# AI 情报日报 — 2026-10-06\n## 今日重点\n'
                               '### 1. Agent\n**来源**：[source](https://example.org/release)\n'
                               '**来源明确说了什么**：' + '有依据的功能说明。'*20
                               + '\n**已知限制**：只取得摘录。\n**对我的意义**：了解即可。'
                               '\n## 简讯\n暂无其他。\n## 今晚行动\n今日无高质量行动机会。')
                else:
                    content = '# AI 情报日报 — 1999-01-01\n### 空标题\n' + 'x'*2100
                if secondary_source:
                    content = content.replace('https://example.org/release', 'https://example.org/secondary')
                path.write_text(content, encoding='utf-8')
                return SimpleNamespace(returncode=cli_exit, stdout='API Error: 402' if cli_exit else '', stderr='')
            tree = ast.parse((ROOT/'generate_report.py').read_text(encoding='utf-8'))
            nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
            ns = dict(argparse=argparse, json=json, os=os, re=re, subprocess=SimpleNamespace(
                run=fake_cli, TimeoutExpired=subprocess.TimeoutExpired, CREATE_NO_WINDOW=0, PIPE=subprocess.PIPE), sys=sys,
                time=time, datetime=datetime, timedelta=timedelta, Path=Path,
                validate_claim_wording=validate_claim_wording,
                BASE_DIR=base, REPORT_FILE=final, REPORT_DIR=final.parent, VAULT_PATH=final.parent,
                TODAY='2026-10-06', DATA_FILE=data_file, TEMP_PROMPT=base/'prompt.txt', MAX_ITEMS=8,
                slog=NullLogger(), timer=NullLogger(), rw=SimpleNamespace(write=archive),
                trend_memory=SimpleNamespace(_data={'total_days': 0}, extract_signals=lambda c: {
                    'keywords': [], 'entities': [], 'themes': []}, update=lambda **k: updates.append(k),
                    write=lambda: None))
            exec(compile(ast.Module(body=nodes, type_ignores=[]), '<mock-orchestrator>', 'exec'), ns)
            ns.update(log=lambda *a: None, step=lambda *a: None,
                      resolve_output_path=output_path, merge_user_path=lambda: None,
                      validate_system_clock=lambda p: (True, ''), wait_for_network=lambda: True,
                      _write_pipeline_status=lambda *a, **k: None, start_http_server=lambda p: None,
                      _wait_for_all_domains=lambda *a: None, _generate_health_log=lambda **k: None,
                      write_health=lambda *a: {'grade': 'A', 'score': 100},
                      read_claudian_config=lambda p: ('fake-claude', None), resolve_model=lambda: None,
                      classify_claude_error=lambda *a: ('api_balance', 'balance'),
                      dump_claude_io=lambda *a: None, tail=lambda s: s,
                      agent_draft_staging_dir=agent_draft_staging_dir,
                      archive_agent_draft=archive_agent_draft,
                      enrich_priority_evidence=lambda items: [dict(i, _evidence_status='excerpt',
                          _evidence_text='Original evidence for ' + i['link']) for i in items])
            with patch.object(sys, 'argv', ['generate_report.py']), patch.object(sys, 'path', sys.path[:]):
                if complete:
                    ns['main']()
                    if previous_broken:
                        ns['REPORT_FILE'] = final
                        ns['main']()
                        self.assertEqual(len(calls), 2, 'A valid numbered report must prevent another fetch/CLI run')
                else:
                    with self.assertRaises(SystemExit) as raised:
                        ns['main']()
                    self.assertEqual(raised.exception.code, 1)
            self.assertEqual(expected.exists(), complete)
            self.assertEqual(bool(updates), complete)
            self.assertEqual((base/'memory/ai/published_sources.json').exists(), complete)
            self.assertEqual(len(list((base/'reports/ai/drafts').glob('*.md'))), 1)
            if secondary_source:
                evidence_path = next((base/'reports/ai/drafts').glob('*.evidence.json'))
                supplied = json.loads(evidence_path.read_text(encoding='utf-8'))['items']
                self.assertEqual(len(supplied), 1)
                source = next(s for s in supplied[0]['_merged_evidence']
                              if s['link'] == 'https://example.org/secondary')
                self.assertEqual(source['_evidence_text'],
                                 'Original evidence for https://example.org/secondary')
                self.assertEqual(source['_evidence_status'], 'excerpt')

    def test_invalid_draft_does_not_publish_or_update_memory(self):
        self.run_pipeline(False, 0)

    def test_complete_draft_survives_cli_error(self):
        self.run_pipeline(True, 1)

    def test_valid_numbered_report_prevents_repeated_retry(self):
        self.run_pipeline(True, 0, previous_broken=True)

    def test_secondary_source_evidence_survives_merge_and_publication(self):
        self.run_pipeline(True, 0, secondary_source=True)


if __name__ == '__main__':
    unittest.main()
