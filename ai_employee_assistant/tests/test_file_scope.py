"""Exercise production scope code without opening the real DB or calling models."""
import ast
import os
import re
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, AsyncMock, patch
from typing import Optional, Literal

from fastapi import HTTPException, Depends
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]


def load_definitions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text())
    nodes = [node for node in tree.body if getattr(node, 'name', None) in names]
    for node in nodes:
        if hasattr(node, 'decorator_list'):
            node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), namespace)
    return namespace


class QueryScopeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rag = types.ModuleType('app.rag')
        self.rag.generate_answer = Mock(return_value={'answer': 'Evidence', 'source_documents': ['policy.pdf']})
        self.rl = types.ModuleType('app.rl_engine')
        self.rl.auto_reward_execution = Mock()
        self.router = types.ModuleType('scripts.llm_router')
        self.router.ask_llm = Mock(return_value='Combined evidence')
        self.modules = patch.dict('sys.modules', {'app.rag': self.rag, 'app.rl_engine': self.rl, 'scripts.llm_router': self.router})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.ns = load_definitions('app/main.py', {'QueryRequest', 'query_assistant'}, {
            'BaseModel': BaseModel, 'Field': Field, 'Literal': Literal, 'Optional': Optional,
            'Session': object, 'Depends': Depends, 'get_db': Mock(), 'get_current_user': Mock(),
            'HTTPException': HTTPException, 'os': os, 'UPLOAD_DIR': '/fake/uploads',
            '_get_uploaded_data_files': Mock(return_value=['a.csv', 'b.csv', 'secret.csv', 'policy.pdf']),
            '_find_best_file': Mock(return_value='secret.csv'),
            '_markdown_to_clean_html': lambda value: value,
            'analyze_data_file': Mock(return_value={'analysis': 'Evidence', 'summary': {'rows': 2}}),
            'log_action': Mock(), 'run_agent': AsyncMock(),
        })

    async def query(self, mode, files, question='Compare all files'):
        request = self.ns['QueryRequest'](question=question, file_scope=mode, selected_files=files, session_id=1)
        return await self.ns['query_assistant'](request, db=Mock(), user={'username': 'tester'})

    async def test_single_selection_overrides_plural_prompt_and_router(self):
        result = await self.query('selected', ['b.csv'])
        self.assertEqual(result['file_used'], 'b.csv')
        self.ns['_find_best_file'].assert_not_called()
        self.ns['analyze_data_file'].assert_called_once_with('/fake/uploads/b.csv', 'Compare all files')

    async def test_multi_selection_never_adds_other_files(self):
        result = await self.query('selected', ['a.csv', 'b.csv', 'a.csv'])
        self.assertEqual(result['files_used'], ['a.csv', 'b.csv'])
        self.assertEqual(self.ns['analyze_data_file'].call_count, 2)
        self.assertNotIn('secret.csv', self.router.ask_llm.call_args.args[0])

    async def test_all_mode_includes_every_file(self):
        result = await self.query('all', [], 'Summarize')
        self.assertEqual(set(result['files_used']), {'a.csv', 'b.csv', 'secret.csv', 'policy.pdf'})
        self.rag.generate_answer.assert_called_once_with('Summarize', filenames=['policy.pdf'])

    async def test_empty_or_unknown_selection_rejected(self):
        for selected in ([], ['missing.pdf'], ['../secret.csv']):
            with self.assertRaises(HTTPException) as error:
                await self.query('selected', selected)
            self.assertEqual(error.exception.status_code, 400)

    async def test_pdf_selection_reaches_retriever(self):
        await self.query('selected', ['policy.pdf'])
        self.rag.generate_answer.assert_called_once_with('Compare all files', filenames=['policy.pdf'])

    async def test_email_request_reaches_agent_with_scoped_evidence(self):
        self.ns['run_agent'].return_value = {'answer': 'Email draft'}
        result = await self.query('selected', ['policy.pdf'], 'Draft this and email it to recipient@example.com')
        self.assertEqual(result['answer'], 'Email draft')
        self.ns['run_agent'].assert_awaited_once()
        context = self.ns['run_agent'].call_args.kwargs['file_context']
        self.assertIn('policy.pdf', context)
        self.assertNotIn('secret.csv', context)
        self.rag.generate_answer.assert_called_once()
        self.assertEqual(self.rag.generate_answer.call_args.kwargs['filenames'], ['policy.pdf'])

    async def test_failed_selected_analysis_cannot_fall_back_to_agent(self):
        self.ns['analyze_data_file'].side_effect = RuntimeError('analysis unavailable')
        with self.assertRaises(HTTPException) as error:
            await self.query('selected', ['a.csv', 'b.csv'])
        self.assertEqual(error.exception.status_code, 503)
        self.ns['run_agent'].assert_not_called()


class EmailApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_email_tool_is_proposed_but_never_executed_before_approval(self):
        ns = load_definitions('app/agent.py', {'run_agent'}, {
            're': re, 'json': json,
            'get_relevant_tools': AsyncMock(return_value=[{'name': 'send_email'}, {'name': 'search_company_knowledge'}]),
            '_format_tools': lambda tools: str(tools),
            'ask_llm': Mock(return_value='tool call'),
            '_extract_tool_call': lambda response: ('send_email', {'to': 'recipient@example.com', 'subject': 'Draft', 'body': 'Evidence'}),
            'tool_requires_approval': lambda name: True,
            '_approval_description': lambda name: 'send an email',
            'call_tool_on_client': AsyncMock(),
        })
        result = await ns['run_agent']('Email this to recipient@example.com', 'tester', 1, file_context='Selected file evidence')
        self.assertEqual(result['mode'], 'pending_approval')
        self.assertEqual(result['tool_name'], 'send_email')
        ns['call_tool_on_client'].assert_not_awaited()
        self.assertNotIn("'name': 'search_company_knowledge'", ns['ask_llm'].call_args.args[0])


class RetrievalScopeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.collection = Mock()
        self.collection.query.return_value = {'documents': [['allowed evidence', 'secret evidence']], 'metadatas': [[{'filename': 'allowed.pdf'}, {'filename': 'secret.pdf'}]]}
        self.ns = load_definitions('app/rag.py', {'generate_answer'}, {
            'os': os, 'UPLOAD_DIR': self.directory.name, 'collection': self.collection,
            'get_embedding': Mock(return_value=[0.1]), 'clean_text': lambda text: text,
            '_extract_text_from_pdf': Mock(return_value='fallback evidence'),
            'search_web': Mock(), 'ask_llm': Mock(return_value='Answer'),
        })

    def test_filters_index_and_defensively_excludes_unselected_results(self):
        result = self.ns['generate_answer']('Question', filenames=['allowed.pdf'])
        self.assertEqual(result['source_documents'], ['allowed.pdf'])
        self.assertEqual(self.collection.query.call_args.kwargs['where'], {'filename': {'$in': ['allowed.pdf']}})
        self.assertNotIn('secret evidence', self.ns['ask_llm'].call_args.args[0])

    def test_index_failure_fallback_reads_only_selected_pdf(self):
        for name in ['allowed.pdf', 'secret.pdf']:
            (Path(self.directory.name) / name).touch()
        self.collection.query.side_effect = RuntimeError('index unavailable')
        self.ns['generate_answer']('Question', filenames=['allowed.pdf'])
        self.ns['_extract_text_from_pdf'].assert_called_once_with(os.path.join(self.directory.name, 'allowed.pdf'))
        self.ns['search_web'].assert_not_called()

    def test_missing_evidence_never_uses_web_or_other_pdf(self):
        (Path(self.directory.name) / 'secret.pdf').touch()
        self.collection.query.return_value = None
        result = self.ns['generate_answer']('Question', filenames=['allowed.pdf'])
        self.assertEqual(result['source_documents'], [])
        self.ns['_extract_text_from_pdf'].assert_not_called()
        self.ns['search_web'].assert_not_called()
        self.ns['ask_llm'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
