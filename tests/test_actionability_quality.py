"""Offline regression checks for actionable recommendations and project claims."""

import unittest

from domains.ai.actionability import classify_actionability
from domains.ai.project_extractor import extract_reproducible_projects


class ActionabilityQualityTests(unittest.TestCase):
    def item(self, description="", **fields):
        return {
            "title": "Example AI tool",
            "description": description,
            "link": "https://github.com/example/tool",
            "source_name": "GitHub Trending Python",
            **fields,
        }

    def classify(self, item):
        return classify_actionability([item])[0]

    def public_demo(self, **fields):
        description = "Free public online demo: https://example.org/demo. No signup required."
        return self.item(
            description,
            _evidence_status="excerpt",
            _evidence_url="https://github.com/example/tool",
            _evidence_text=description,
            **fields,
        )

    def test_repository_and_empty_description_are_not_evidence_of_access(self):
        item = self.classify(self.item())
        self.assertEqual(item["_actionability"], "B")
        self.assertIn("待核验", item["_actionability_reason"])
        self.assertFalse(item["_has_public_url"])

    def test_source_or_marketing_words_do_not_make_a_product_usable(self):
        for description in ("An open source AI tool, released today", "Free AI framework"):
            with self.subTest(description=description):
                self.assertNotEqual(self.classify(self.item(description))["_actionability"], "A")

    def test_restrictions_override_demo_and_github(self):
        for restriction in (
            "Private beta; contact sales",
            "Paid subscription required",
            "Requires account",
            "Requires GPU cluster",
            "Run pip install example-tool",
        ):
            with self.subTest(restriction=restriction):
                item = self.public_demo()
                item["description"] += " " + restriction
                item["_evidence_text"] += " " + restriction
                self.assertEqual(self.classify(item)["_actionability"], "B")

    def test_fetched_public_demo_is_actionable_without_signup(self):
        item = self.classify(self.public_demo())
        self.assertEqual(item["_actionability"], "A")
        self.assertFalse(item["_requires_account"])
        self.assertEqual(item["_action_url"], "https://example.org/demo")

    def test_unfetched_demo_is_not_verified(self):
        item = self.public_demo()
        item["_evidence_status"] = "unavailable"
        self.assertEqual(self.classify(item)["_actionability"], "B")

    def test_navigation_demo_does_not_invent_a_product_entry(self):
        item = self.public_demo()
        item["description"] = "An AI library for document processing"
        self.assertNotEqual(self.classify(item)["_actionability"], "A")

    def test_paid_evidence_cannot_be_hidden_by_an_optimistic_summary(self):
        item = self.public_demo()
        item["_evidence_text"] += " Paid subscription required."
        classified = self.classify(item)
        self.assertEqual(classified["_actionability"], "B")
        self.assertTrue(classified["_requires_payment"])

    def test_installation_remains_a_possible_assisted_action(self):
        item = self.classify(self.item("Open source tool. Run pip install example-tool."))
        self.assertEqual(item["_actionability"], "B")
        self.assertTrue(item["_requires_setup"])
        self.assertNotIn("不可用", item["_actionability_reason"])

    def test_project_card_does_not_invent_reproduction_or_effort(self):
        for item in (self.item(), self.item("Open source framework, pip install example-tool")):
            with self.subTest(description=item["description"]):
                cards = extract_reproducible_projects(classify_actionability([item]))
                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0]["reproducible"], "Unknown")
                self.assertEqual(cards[0]["reproduction_cost"], {"time": "Unknown", "difficulty": "Unknown"})

    def test_online_demo_is_not_proof_of_source_reproducibility(self):
        item = self.classify(self.public_demo())
        card = extract_reproducible_projects([item])[0]
        self.assertEqual(card["reproducible"], "Unknown")
        self.assertEqual(card["actionability"], item["_actionability"])
        self.assertEqual(card["availability_reason"], item["_actionability_reason"])


if __name__ == "__main__":
    unittest.main()
