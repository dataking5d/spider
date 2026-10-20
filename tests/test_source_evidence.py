import ast
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class Response:
    headers = {'Content-Type': 'text/html; charset=utf-8'}
    url = 'https://example.org/source'

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield ('<html><nav>fake unrelated demo</nav><article>' + 'Grounded source content. ' * 40
               + '<a href="/demo">Free public online demo, no account required</a>'
               + '</article></html>').encode('utf-8')


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT/'generate_report.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'enrich_priority_evidence')
        self.messages = []
        namespace = {'datetime': datetime, 'log': self.messages.append}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<offline-evidence>', 'exec'), namespace)
        self.enrich = namespace[node.name]

    def test_only_three_sources_and_preserves_real_links(self):
        items = [{'link': f'https://example.org/{n}', '_total_score': n} for n in range(5)]
        with patch('requests.get', return_value=Response()) as get:
            self.enrich(items)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([i['_evidence_status'] for i in items], ['summary_only']*2 + ['excerpt']*3)
        self.assertIn('https://example.org/demo', items[-1]['_evidence_text'])
        self.assertNotIn('fake unrelated', items[-1]['_evidence_text'])

    def test_failed_request_remains_summary_only(self):
        import requests
        item = {'link': 'https://example.org/down', 'title': 'source', 'description': 'Original summary'}
        with patch('requests.get', side_effect=requests.Timeout('offline timeout')):
            self.enrich([item])
        self.assertEqual(item['_evidence_status'], 'summary_only')
        self.assertEqual(item['description'], 'Original summary')
        self.assertNotIn('_evidence_text', item)
        self.assertTrue(self.messages)

    def test_highest_two_sources_keep_a_slot_for_lower_scored_tool(self):
        items = [
            {'title': 'Vendor release', 'link': 'https://example.org/first', '_total_score': 100},
            {'title': 'Vendor guide', 'link': 'https://example.org/second', '_total_score': 90},
            {'title': 'Customer case', 'link': 'https://example.org/third', '_total_score': 80},
            {'title': 'AI workflow tool', 'link': 'https://github.com/example/tool', '_total_score': 10},
        ]
        with patch('requests.get', return_value=Response()) as get:
            self.enrich(items)
        self.assertEqual([call.args[0] for call in get.call_args_list],
                         [items[0]['link'], items[1]['link'], items[3]['link']])
        self.assertEqual([item['_total_score'] for item in items], [100, 90, 80, 10])
        self.assertEqual(items[2]['_evidence_status'], 'summary_only')

    def test_repository_preferred_to_generic_tool_with_no_extra_requests(self):
        items = [{'link': f'https://example.org/{n}', '_total_score': 100-n}
                 for n in range(3)]
        items.extend([
            {'link': 'https://example.org/tool', 'description': 'Open-source AI workflow tool', '_total_score': 20},
            {'link': 'https://github.com/example/tool', '_total_score': 10},
        ])
        with patch('requests.get', return_value=Response()) as get:
            self.enrich(items)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args_list[-1].args[0], items[-1]['link'])

    def test_open_source_tool_uses_reserved_slot_when_no_repository(self):
        items = [{'link': f'https://example.org/{n}', '_total_score': 100-n}
                 for n in range(3)]
        items.append({'link': 'https://example.org/tool',
                      'description': 'Open-source AI workflow tool', '_total_score': 10})
        with patch('requests.get', return_value=Response()) as get:
            self.enrich(items)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(get.call_args_list[-1].args[0], items[-1]['link'])

    def test_captcha_not_treated_as_evidence(self):
        response = Response()
        response.iter_content = lambda size: [b'<main>Verify you are human. ' + b'x'*500 + b'</main>']
        item = {'link': 'https://example.org/challenge'}
        with patch('requests.get', return_value=response):
            self.enrich([item])
        self.assertEqual(item['_evidence_status'], 'summary_only')


if __name__ == '__main__':
    unittest.main()
