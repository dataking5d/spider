import ast
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from domains.claim_checks import validate_claim_wording

ROOT = Path(__file__).resolve().parents[1]


def functions_from_generator():
    tree = ast.parse((ROOT / 'generate_report.py').read_text(encoding='utf-8'))
    names = {'_report_urls', 'validate_ai_report', 'publish_ai_draft', 'record_published_sources'}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = {'re': re, 'json': json, 'datetime': datetime, 'timedelta': timedelta,
                 'Path': Path, 'validate_claim_wording': validate_claim_wording}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<offline-generator>', 'exec'), namespace)
    return namespace


class AIReportQualityTests(unittest.TestCase):
    def setUp(self):
        self.fn = functions_from_generator()
        self.url = 'https://example.org/release'
        self.item = {'title': 'Agent release', 'link': self.url, 'description': 'New public release',
                     '_evidence_status': 'excerpt'}
        self.good = ('# AI 情报日报 — 2026-10-06\n\n## 今日重点\n\n### 1. 工具发布\n'
                     '**来源**：[原文](https://example.org/release)\n'
                     '**来源明确说了什么**：' + '明确的已发布能力以及证据。' * 10 + '\n'
                     '**已知限制**：仅正文摘录，安装条件尚待核验。\n'
                     '**对我的意义**：可以了解功能，不建议马上部署。\n'
                     '## 简讯\n暂无其他合格新信息。\n## 今晚行动\n今日无高质量行动机会。')

    def test_validation_available(self):
        self.assertIn('validate_ai_report', self.fn)

    def test_good_report(self):
        self.assertEqual(self.fn['validate_ai_report'](self.good, '2026-10-06', [self.item]), [])

    def test_short_wrong_date_and_missing_citation_rejected(self):
        for text in ('# AI 情报日报', self.good.replace('2026-10-06', '1999-01-01'),
                     self.good.replace(self.url, 'https://madeup.example/wrong')):
            with self.subTest(text=text[:30]):
                self.assertTrue(self.fn['validate_ai_report'](text, '2026-10-06', [self.item]))

    def test_summary_only_cannot_be_deep_analysis(self):
        item = {**self.item, '_evidence_status': 'summary_only'}
        self.assertTrue(self.fn['validate_ai_report'](self.good, '2026-10-06', [item]))

    def test_action_requires_available_entry(self):
        content = self.good + '\n### Try it\nOpen https://example.org/demo to run it.'
        self.assertTrue(self.fn['validate_ai_report'](content, '2026-10-06', [self.item]))
        item = {**self.item, '_actionability': 'A', '_action_url': 'https://example.org/demo'}
        self.assertFalse(self.fn['validate_ai_report'](content, '2026-10-06', [item]))

    def test_unstructured_action_cannot_bypass_availability_check(self):
        content = self.good.replace('今日无高质量行动机会。', '- 今晚去注册 https://madeup.example 并付费使用。')
        self.assertTrue(self.fn['validate_ai_report'](content, '2026-10-06', [self.item]))

    def test_empty_boundary_labels_do_not_make_a_complete_item(self):
        content = self.good.replace('仅正文摘录，安装条件尚待核验。', '')
        self.assertTrue(self.fn['validate_ai_report'](content, '2026-10-06', [self.item]))

    def test_claim_checks_receive_facts_not_personal_suggestions(self):
        calls = []
        self.fn['validate_claim_wording'] = lambda claim, evidence_text, source_url='': (
            calls.append((claim, evidence_text, source_url)) or [])
        item = {**self.item, '_evidence_text': 'Original source excerpt'}
        self.assertFalse(self.fn['validate_ai_report'](self.good, '2026-10-06', [item]))
        self.assertEqual(len(calls), 1)
        claim, evidence, source = calls[0]
        self.assertIn('明确的已发布能力', claim)
        self.assertNotIn('不建议马上部署', claim)
        self.assertEqual((evidence, source), ('Original source excerpt', self.url))

    def test_claim_cannot_borrow_evidence_from_another_item(self):
        item = {**self.item, '_evidence_text': '200-token passages'}
        unrelated = {**self.item, 'link': 'https://example.org/unrelated',
                     '_evidence_text': '200 words in a different study'}
        self.fn['validate_claim_wording'] = lambda claim, evidence_text, source_url='': (
            ['Unit changed for this source'] if evidence_text == '200-token passages' else [])
        errors = self.fn['validate_ai_report'](self.good, '2026-10-06', [item, unrelated])
        self.assertIn('Unit changed for this source', ' '.join(errors))

    def test_cited_secondary_source_uses_its_own_excerpt(self):
        secondary = {**self.item, 'link': 'https://example.org/secondary',
                     '_evidence_text': 'Secondary original excerpt'}
        item = {**self.item, '_evidence_text': 'Primary original excerpt',
                '_merged_evidence': [self.item, secondary]}
        calls = []
        self.fn['validate_claim_wording'] = lambda claim, evidence_text, source_url='': (
            calls.append((evidence_text, source_url)) or [])
        errors = self.fn['validate_ai_report'](self.good.replace(self.url, secondary['link']),
                                              '2026-10-06', [item])
        self.assertFalse(errors)
        self.assertEqual(calls, [('Secondary original excerpt', secondary['link'])])

    def test_summary_claim_checks_use_only_its_original_summary(self):
        content = ('# AI 情报日报 — 2026-10-06\n## 今日重点\n今日无合格新信息。\n'
                   '## 简讯\n### 1. 社区转述\n**来源**：[原文](https://example.org/release)\n'
                   + '这是一条未经官方确认的社区转述，不应替代官方规则或推导普遍适用的限制。' * 2
                   + '\n## 今晚行动\n今日无高质量行动机会。')
        calls = []
        self.fn['validate_claim_wording'] = lambda claim, evidence_text, source_url='': (
            calls.append(evidence_text) or [])
        item = {**self.item, '_evidence_status': 'summary_only', 'description': 'Community anecdote'}
        self.assertFalse(self.fn['validate_ai_report'](content, '2026-10-06', [item]))
        self.assertEqual(calls, ['Community anecdote'])

    def test_claim_error_blocks_publication(self):
        self.fn['validate_claim_wording'] = lambda *a, **kw: ['Unsupported numerical wording']
        with tempfile.TemporaryDirectory() as directory:
            draft, final = Path(directory)/'draft.md', Path(directory)/'final.md'
            draft.write_text(self.good, encoding='utf-8')
            self.assertTrue(self.fn['publish_ai_draft'](draft, final, '2026-10-06', [self.item]))
            self.assertFalse(final.exists())

    def test_empty_day_with_explanation(self):
        empty = ('# AI 情报日报 — 2026-10-06\n## 今日重点\n今日无合格新信息。'
                 '已检查今日候选，内容均为没有实质变化的旧资料；不把旧文当作新发布。'
                 '\n## 简讯\n部分来源未能取得正文，无法确定具体能力和费用，故未扩写。'
                 '\n## 今晚行动\n今日无高质量行动机会。')
        self.assertFalse(self.fn['validate_ai_report'](empty, '2026-10-06', []))

    def test_invalid_draft_never_published(self):
        with tempfile.TemporaryDirectory() as d:
            draft, final = Path(d)/'draft.md', Path(d)/'final.md'
            draft.write_text('### empty\n' * 70, encoding='utf-8')
            errors = self.fn['publish_ai_draft'](draft, final, '2026-10-06', [self.item])
            self.assertTrue(errors)
            self.assertFalse(final.exists())
            self.assertTrue(draft.exists())

    def test_valid_draft_can_publish_without_cli_success(self):
        with tempfile.TemporaryDirectory() as d:
            draft, final = Path(d)/'draft.md', Path(d)/'final.md'
            draft.write_text(self.good, encoding='utf-8')
            self.assertFalse(self.fn['publish_ai_draft'](draft, final, '2026-10-06', [self.item]))
            self.assertEqual(final.read_text(encoding='utf-8'), self.good)
            self.assertTrue(self.fn['publish_ai_draft'](draft, final, '2026-10-06', [self.item]))

    def test_record_only_published_sources(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'published.json'
            other = {'link': 'https://example.org/not_selected', 'title': 'Other', 'description': 'not selected'}
            self.fn['record_published_sources'](self.good, [self.item, other], path, '2026-10-06')
            records = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual([r['link'] for r in records], [self.url])

    def test_record_cited_secondary_source_without_marking_uncited_primary(self):
        secondary = {**self.item, 'link': 'https://example.org/secondary'}
        item = {**self.item, '_merged_evidence': [self.item, secondary]}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'published.json'
            self.fn['record_published_sources'](self.good.replace(self.url, secondary['link']),
                                                [item], path, '2026-10-06')
            records = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual([r['link'] for r in records], [secondary['link']])


if __name__ == '__main__':
    unittest.main()
