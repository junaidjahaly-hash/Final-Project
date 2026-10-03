import unittest
from unittest.mock import AsyncMock, patch

from app import semantic_routing as routing
from app.agent import get_relevant_tools


class SemanticRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_paraphrase_discovers_server_and_tool_without_keywords(self):
        tool = {"name": "send_email", "raw_name": "send_email", "server": "internal",
                "description": "Send correspondence", "schema": {}}
        with patch("app.semantic_routing.similarities", AsyncMock(side_effect=[
            [0.8, 0.1, 0.1, 0.1, 0.1], [0.8]
        ])), patch("app.agent._discover_tools", AsyncMock(return_value=[tool])) as discover:
            result = await get_relevant_tools("Let Sarah know I cannot attend")
        self.assertEqual(discover.call_args.args[0], ["internal"])
        self.assertEqual(result[0]["name"], "send_email")

    async def test_low_evidence_does_not_choose_arbitrary_tool(self):
        tool = {"name": "send_email", "raw_name": "send_email", "server": "internal",
                "description": "Send correspondence", "schema": {}}
        with patch("app.semantic_routing.similarities", AsyncMock(return_value=None)), \
                patch("app.agent._discover_tools", AsyncMock(return_value=[tool])):
            self.assertEqual(await get_relevant_tools("Explain compound interest"), [])

    async def test_embedding_failure_backs_off(self):
        import httpx
        routing._retry_after = 0
        routing._cache.clear()
        with patch.object(httpx.AsyncClient, "post", AsyncMock(side_effect=httpx.ConnectError("offline"))) as post:
            self.assertIsNone(await routing.similarities("hello", ["test"]))
            self.assertIsNone(await routing.similarities("again", ["test"]))
            self.assertEqual(post.await_count, 1)
        routing._retry_after = 0

    def test_competing_matches_ask_for_clarification(self):
        tools = [{"name": "send_email", "semantic_score": .7, "lexical_score": 0},
                 {"name": "create_support_ticket", "semantic_score": .69, "lexical_score": 0}]
        self.assertIn("clarify", routing.clarification(tools))
        tools[0]["lexical_score"] = 12
        self.assertIsNone(routing.clarification(tools))
