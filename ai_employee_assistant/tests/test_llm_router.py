import unittest
from unittest.mock import patch

from scripts import llm_router


class LLMRouterThinkingTests(unittest.TestCase):
    def test_fast_tier_disables_thinking(self):
        with patch.object(llm_router, "_call_ollama", return_value="hello") as call:
            answer = llm_router.ask_llm("hello", max_tokens=60, tier="fast")

        self.assertEqual(answer, "hello")
        self.assertFalse(call.call_args.kwargs["think"])

    def test_main_cloud_disables_hidden_reasoning(self):
        with patch.object(llm_router, "_call_ollama", return_value="analysis") as call:
            answer = llm_router.ask_llm("Analyze this report", max_tokens=200, tier="main")

        self.assertEqual(answer, "analysis")
        self.assertFalse(call.call_args.kwargs["think"])

    def test_heavy_cloud_keeps_default_reasoning(self):
        with patch.object(llm_router, "_call_ollama", return_value="deep analysis") as call:
            answer = llm_router.ask_llm("Audit this ledger", max_tokens=400, tier="heavy")

        self.assertEqual(answer, "deep analysis")
        self.assertIsNone(call.call_args.kwargs["think"])

    def test_local_9b_main_disables_hidden_reasoning(self):
        with (
            patch.object(llm_router.settings, "CLOUD_FIRST_FOR_MAIN", False),
            patch.object(llm_router, "_call_ollama", return_value="local answer") as call,
        ):
            answer = llm_router.ask_llm("Summarize this", max_tokens=200, tier="main")

        self.assertEqual(answer, "local answer")
        self.assertEqual(call.call_args.args[0], llm_router.settings.LOCAL_MAIN_MODEL)
        self.assertFalse(call.call_args.kwargs["think"])


if __name__ == "__main__":
    unittest.main()
