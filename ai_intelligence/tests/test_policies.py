# ai_intelligence/tests/test_policies.py
"""Tests for the shared policy rules and their inclusion in the chat system prompt."""
from django.test import SimpleTestCase

from ai_intelligence.domain.policies import ALL_RULES, NO_FINANCIAL_ADVICE_RULE, render_rules
from ai_intelligence.prompts.system import BASE_SYSTEM_PROMPT


class PolicyRenderingTests(SimpleTestCase):
    def test_render_rules_includes_every_rule(self):
        rendered = render_rules()
        for rule in ALL_RULES:
            self.assertIn(rule, rendered)

    def test_system_prompt_includes_no_advice_rule(self):
        self.assertIn(NO_FINANCIAL_ADVICE_RULE, BASE_SYSTEM_PROMPT)