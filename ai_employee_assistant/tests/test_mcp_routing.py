import unittest

from app.agent import (
    _extract_tool_call,
    _score_tool,
    _validate_fetch_arguments,
    route_mcp_servers,
    tool_requires_approval,
)


class MCPRoutingTests(unittest.TestCase):
    def test_routes_only_relevant_servers(self):
        self.assertEqual(route_mcp_servers("hello"), [])
        self.assertEqual(route_mcp_servers("Explain compound interest"), [])
        self.assertIn("internal", route_mcp_servers("Find the HR leave policy"))
        self.assertIn("filesystem", route_mcp_servers("List files in the uploads folder"))
        self.assertIn("memory", route_mcp_servers("Remember my reporting preference"))
        self.assertIn("time", route_mcp_servers("What time is it in London?"))
        self.assertIn("fetch", route_mcp_servers("Read https://example.com/report"))

    def test_tool_scoring_prefers_explicit_intent(self):
        policy_tool = {
            "name": "search_company_knowledge",
            "raw_name": "search_company_knowledge",
            "server": "internal",
            "description": "Search uploaded company policies and documents",
            "schema": {"properties": {"query": {"type": "string"}}},
        }
        ticket_tool = {
            "name": "create_support_ticket",
            "raw_name": "create_support_ticket",
            "server": "internal",
            "description": "Create an employee support ticket",
            "schema": {"properties": {"subject": {"type": "string"}}},
        }
        question = "What does the uploaded HR policy say about leave?"
        self.assertGreater(_score_tool(question, policy_tool), _score_tool(question, ticket_tool))

    def test_mutating_tools_require_approval(self):
        self.assertTrue(tool_requires_approval("filesystem.write_file"))
        self.assertTrue(tool_requires_approval("create_support_ticket"))
        self.assertTrue(tool_requires_approval("memory.delete_entities"))
        self.assertFalse(tool_requires_approval("read_text_file"))
        self.assertFalse(tool_requires_approval("get_current_time"))

    def test_extracts_only_valid_tool_json(self):
        parsed = _extract_tool_call(
            '```json\n{"tool_name":"get_open_tickets","tool_arguments":{}}\n```'
        )
        self.assertEqual(parsed, ("get_open_tickets", {}))
        self.assertIsNone(_extract_tool_call("There is no tool call here."))


class FetchSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_private_addresses(self):
        with self.assertRaises(ValueError):
            await _validate_fetch_arguments("fetch", {"url": "http://127.0.0.1/private"})
        with self.assertRaises(ValueError):
            await _validate_fetch_arguments("fetch", {"url": "http://localhost:8080"})

    async def test_allows_public_literal_address(self):
        await _validate_fetch_arguments("fetch", {"url": "https://8.8.8.8"})


if __name__ == "__main__":
    unittest.main()
