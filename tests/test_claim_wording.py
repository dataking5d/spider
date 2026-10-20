"""Known source-to-note distortions, using the preserved review examples."""
import unittest

from domains.claim_checks import validate_claim_wording


class ClaimWordingTests(unittest.TestCase):
    def test_tokens_cannot_be_relabelled_as_words(self):
        evidence = 'About 80% of 200-token passages and 95% of 400-token passages.'
        self.assertTrue(validate_claim_wording('200词约80%，400词约95%。', evidence))

    def test_token_unit_and_word_editing_percentage_are_valid(self):
        evidence = ('About 80% of 200-token passages. In 400-token passages, '
                    'replacing 10% of words reduced detection to 66%.')
        self.assertEqual(validate_claim_wording(
            '200 token片段检出率80%；替换10%的词后，400 token片段检出率降至66%。', evidence), [])

    def test_token_count_is_not_character_count(self):
        self.assertTrue(validate_claim_wording('400个字符', '400-token passages'))

    def test_unrelated_word_count_is_not_a_token_error(self):
        self.assertEqual(validate_claim_wording('20词摘要', '400-token passages'), [])

    def test_odds_ratio_is_not_a_probability_multiplier(self):
        evidence = 'Openness (odds ratio OR = 1.616), conscientiousness (OR = 1.279).'
        self.assertTrue(validate_claim_wording('开放性提高成功概率约1.6倍。', evidence))
        self.assertTrue(validate_claim_wording('开放性约1.6倍、尽责性约1.28倍，也提高成功概率。', evidence))

    def test_adding_or_label_does_not_repair_a_false_probability_claim(self):
        self.assertTrue(validate_claim_wording('成功概率提高约1.6倍（OR=1.6）。', 'odds ratio OR=1.6'))

    def test_explicit_explanation_of_odds_is_allowed(self):
        self.assertEqual(validate_claim_wording(
            '优势比OR约1.6，不能解释为成功概率提高1.6倍。', 'odds ratio OR=1.616'), [])
        self.assertEqual(validate_claim_wording('开放性与盈利显著相关，OR约1.6。', 'odds ratio OR=1.616'), [])

    def test_relative_risk_is_not_automatically_treated_as_odds(self):
        self.assertEqual(validate_claim_wording('风险约1.6倍。', 'Relative risk was 1.6.'), [])

    def test_reddit_story_is_not_an_official_policy(self):
        self.assertTrue(validate_claim_wording(
            '帖子转述了封号经历。OpenAI条款禁止用其API输出训练模型；此事未获官方确认。',
            'A user says their account was banned.', 'https://www.reddit.com/r/test/comments/1'))

    def test_community_attribution_and_uncertainty_are_preserved(self):
        self.assertEqual(validate_claim_wording(
            '帖子声称因违反条款被封，具体条款及适用范围尚未核实。',
            'A user says their account was banned.', 'https://www.reddit.com/r/test/comments/1'), [])

    def test_primary_source_policy_is_not_rejected_by_community_rule(self):
        self.assertEqual(validate_claim_wording('服务条款禁止某种用途。',
            'These terms prohibit this use.', 'https://example.org/terms'), [])


if __name__ == '__main__':
    unittest.main()
