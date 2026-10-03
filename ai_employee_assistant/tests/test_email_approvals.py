import json
import re
import types
import unittest
from datetime import datetime
from typing import Optional, Literal
from unittest.mock import Mock, AsyncMock, patch

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime
from sqlalchemy.orm import declarative_base, Session
from test_file_scope import load_definitions


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        base = declarative_base()
        model = load_definitions('app/database.py', {'ApprovalRequest'}, {
            'Base': base, 'Column': Column, 'Integer': Integer, 'String': String,
            'JSON': JSON, 'DateTime': DateTime, 'datetime': datetime,
        })['ApprovalRequest']
        self.engine = create_engine('sqlite:///:memory:')
        base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        module = types.ModuleType('app.database')
        module.ApprovalRequest = model
        mocked = patch.dict('sys.modules', {'app.database': module})
        mocked.start()
        self.addCleanup(mocked.stop)
        self.ns = load_definitions('app/main.py', {'QueryRequest', 'ApprovalSubmitRequest', 'approval_payload', 'save_approval', 'pending_approvals', 'approve_tool_call', 'query_assistant'}, {
            'BaseModel': BaseModel, 'Field': Field, 'Optional': Optional, 'Literal': Literal,
            'Session': Session, 'Depends': Depends, 'get_db': Mock(), 'get_current_user': Mock(),
            'HTTPException': HTTPException, 'init_clients': AsyncMock(), 'log_action': Mock(),
            'call_tool_on_client': AsyncMock(return_value=types.SimpleNamespace(content=[types.SimpleNamespace(text='Email physically sent')], isError=False)),
        })
        self.payload = self.ns['save_approval'](self.db, 'owner', 7, 'send_email', {'to':'first@example.com', 'subject':'Policy', 'body':'The original body'})

    async def approve(self, approved=True, user='owner'):
        request = self.ns['ApprovalSubmitRequest'](session_id=7, approval_id=self.payload['approval_id'], approved=approved)
        return await self.ns['approve_tool_call'](request, self.db, {'username':user})

    async def test_restore_then_approve_once(self):
        self.assertEqual(len(self.ns['pending_approvals'](7, self.db, {'username':'owner'})), 1)
        await self.approve()
        with self.assertRaises(HTTPException) as error:
            await self.approve()
        self.assertEqual(error.exception.status_code, 409)
        self.ns['call_tool_on_client'].assert_awaited_once()
        self.assertEqual(self.ns['pending_approvals'](7, self.db, {'username':'owner'}), [])

    async def test_reject_never_calls_tool(self):
        result = await self.approve(False)
        self.assertEqual(result['status'], 'rejected')
        self.ns['call_tool_on_client'].assert_not_awaited()

    async def test_other_user_cannot_approve(self):
        with self.assertRaises(HTTPException) as error:
            await self.approve(user='other')
        self.assertEqual(error.exception.status_code, 404)
        self.ns['call_tool_on_client'].assert_not_awaited()

    async def test_smtp_failure_not_reported_as_success(self):
        self.ns['call_tool_on_client'].return_value.content[0].text = 'Failed to send email: unavailable'
        with self.assertRaises(HTTPException) as error:
            await self.approve()
        self.assertEqual(error.exception.status_code, 502)

    async def test_repeat_preserves_body_and_creates_new_approval(self):
        request = self.ns['QueryRequest'](session_id=7, question='send it also to second@example.com')
        result = await self.ns['query_assistant'](request, self.db, {'username':'owner'})
        self.assertNotEqual(result['approval_id'], self.payload['approval_id'])
        self.assertEqual(result['tool_arguments'], {'to':'second@example.com','subject':'Policy','body':'The original body'})
        self.ns['call_tool_on_client'].assert_not_awaited()

    async def test_typed_approval_restores_card_without_sending(self):
        request = self.ns['QueryRequest'](session_id=7, question='yeah I approve it')
        result = await self.ns['query_assistant'](request, self.db, {'username':'owner'})
        self.assertEqual(result['approval_id'], self.payload['approval_id'])
        self.ns['call_tool_on_client'].assert_not_awaited()

    async def test_draft_only_cannot_send(self):
        ns = load_definitions('app/agent.py', {'run_agent'}, {
            're':re, 'json':json, 'get_relevant_tools': AsyncMock(return_value=[{'name':'send_email'}]),
            '_format_tools':str, 'ask_llm':Mock(return_value=json.dumps({'email_draft':{'to':'','subject':'Subject','body':'Draft body'}})),
            'call_tool_on_client':AsyncMock(),
        })
        result = await ns['run_agent']('Draft an email', 'owner', 7, file_context='Evidence')
        self.assertEqual(result['mode'], 'email_draft')
        ns['call_tool_on_client'].assert_not_awaited()
