import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, Mock

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from reportlab.pdfgen import canvas

from app.database import Base, User, SupportTicket, Reminder, PersonalTask, Notification, ApprovalRequest
from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.workflows import utc_date
from app.analysis_evidence import explain_dataset, analysis_details_html
from app.document_evidence import pdf_pages, page_chunks, citation_for, citations_html


class WorkflowAPITests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([User(username='employee', role='employee'), User(username='other', role='employee'), User(username='admin', role='admin')])
        self.db.commit()
        self.user = {'username': 'employee', 'role': 'employee'}
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def as_user(self, name):
        self.user = {'username': name, 'role': 'admin' if name == 'admin' else 'employee'}

    def create_ticket(self):
        response = self.client.post('/tickets', json={'subject':'Payroll error','description':'Cannot access payroll.','priority':'high'})
        self.assertEqual(response.status_code, 200)
        return response.json()['ticket_id']

    def test_ticket_full_round_trip_and_notifications(self):
        ticket_id = self.create_ticket()
        self.as_user('admin')
        self.assertEqual(self.client.get('/notifications').json()['unread'], 1)
        self.assertEqual(self.client.put(f'/tickets/{ticket_id}', json={'status':'in_progress','assigned_to':'admin'}).status_code, 200)
        self.assertEqual(self.client.post(f'/tickets/{ticket_id}/replies', json={'body':'Please restart your browser.'}).status_code, 200)
        self.as_user('employee')
        conversation = self.client.get(f'/tickets/{ticket_id}/conversation').json()
        self.assertEqual(conversation['status'], 'in_progress')
        self.assertEqual(conversation['assigned_to'], 'admin')
        self.assertEqual(conversation['replies'][0]['username'], 'admin')
        self.assertEqual(self.client.get('/notifications').json()['unread'], 2)
        self.assertEqual(self.client.post(f'/tickets/{ticket_id}/replies', json={'body':'It works now.'}).status_code, 200)
        self.as_user('admin')
        self.client.put(f'/tickets/{ticket_id}', json={'status':'resolved'})
        self.as_user('employee')
        self.assertEqual(self.client.get(f'/tickets/{ticket_id}/conversation').json()['status'], 'resolved')

    def test_ticket_access_and_admin_controls(self):
        ticket_id = self.create_ticket()
        self.as_user('other')
        self.assertEqual(self.client.get('/tickets').json(), [])
        self.assertEqual(self.client.get(f'/tickets/{ticket_id}/conversation').status_code, 404)
        self.assertEqual(self.client.post(f'/tickets/{ticket_id}/replies', json={'body':'Intrusion'}).status_code, 404)
        self.assertEqual(self.client.put(f'/tickets/{ticket_id}', json={'status':'resolved'}).status_code, 403)
        self.assertEqual(self.client.get('/users/assignees').status_code, 403)

    def test_assignment_validation_and_unassign(self):
        ticket_id = self.create_ticket()
        self.as_user('admin')
        self.assertEqual(self.client.put(f'/tickets/{ticket_id}', json={'assigned_to':'missing'}).status_code, 400)
        self.assertEqual(self.client.put(f'/tickets/{ticket_id}', json={'status':'invented'}).status_code, 422)
        self.client.put(f'/tickets/{ticket_id}', json={'assigned_to':'other'})
        self.as_user('other')
        self.assertEqual(self.client.get('/tickets').json()[0]['id'], ticket_id)
        self.as_user('admin')
        self.client.put(f'/tickets/{ticket_id}', json={'assigned_to':''})
        self.assertIsNone(self.db.get(SupportTicket, ticket_id).assigned_to)

    def test_due_reminders_and_tasks_are_delivered_once(self):
        past = datetime.utcnow() - timedelta(minutes=1)
        self.db.add_all([Reminder(username='employee',message='Call HR',due_date=past), PersonalTask(username='employee',title='Review report',due_date=past), PersonalTask(username='employee',title='Already done',due_date=past,is_done=True), Reminder(username='other',message='Private',due_date=past)])
        self.db.commit()
        data = self.client.get('/notifications').json()
        self.assertEqual(data['unread'], 2)
        self.assertEqual(self.client.get('/notifications').json()['unread'], 2)
        self.client.post('/notifications/read-all')
        self.assertEqual(self.client.get('/notifications').json()['unread'], 0)
        self.as_user('other')
        self.assertEqual(self.client.put(f"/notifications/{data['items'][0]['id']}/read").status_code, 404)

    def test_owner_can_delete_resolved_ticket_and_related_records(self):
        ticket_id = self.create_ticket()
        self.as_user('admin')
        self.client.post(f'/tickets/{ticket_id}/replies', json={'body':'Solved.'})
        self.client.put(f'/tickets/{ticket_id}', json={'status':'resolved'})
        self.as_user('employee')
        self.assertEqual(self.client.delete(f'/tickets/{ticket_id}').status_code, 200)
        self.assertIsNone(self.db.query(SupportTicket).filter_by(id=ticket_id).first())
        from app.database import TicketReply
        self.assertEqual(self.db.query(TicketReply).filter_by(ticket_id=ticket_id).count(), 0)
        self.assertEqual(self.db.query(Notification).filter_by(kind='ticket',resource_id=ticket_id).count(), 0)

    def test_escalated_ticket_can_be_deleted_by_creator_or_admin(self):
        for account in ('employee', 'admin'):
            self.as_user('employee')
            ticket_id = self.create_ticket()
            self.as_user('admin')
            self.client.put(f'/tickets/{ticket_id}', json={'status':'escalated'})
            self.as_user(account)
            self.assertEqual(self.client.delete(f'/tickets/{ticket_id}').status_code, 200)
            self.assertIsNone(self.db.query(SupportTicket).filter_by(id=ticket_id).first())

    def test_unresolved_ticket_cannot_be_deleted(self):
        ticket_id = self.create_ticket()
        self.assertEqual(self.client.delete(f'/tickets/{ticket_id}').status_code, 409)
        self.assertIsNotNone(self.db.get(SupportTicket, ticket_id))

    def test_assignee_cannot_delete_someone_elses_ticket(self):
        ticket_id = self.create_ticket()
        self.as_user('admin')
        self.client.put(f'/tickets/{ticket_id}', json={'status':'resolved','assigned_to':'other'})
        self.as_user('other')
        self.assertEqual(self.client.delete(f'/tickets/{ticket_id}').status_code, 403)
        self.assertIsNotNone(self.db.get(SupportTicket, ticket_id))

    def test_admin_can_delete_resolved_ticket(self):
        ticket_id = self.create_ticket()
        self.as_user('other')
        self.assertEqual(self.client.delete(f'/tickets/{ticket_id}').status_code, 404)
        self.as_user('admin')
        self.client.put(f'/tickets/{ticket_id}', json={'status':'resolved'})
        self.assertEqual(self.client.delete(f'/tickets/{ticket_id}').status_code, 200)

    def test_task_lifecycle_and_ownership(self):
        task = self.client.post('/tasks', json={'title':'Review report','due_date':'2026-10-04T10:00:00+04:00'}).json()
        self.assertEqual(task['due_date'], '2026-10-04T06:00:00Z')
        self.assertEqual(self.client.put(f"/tasks/{task['id']}", json={'is_done':True}).json()['is_done'], True)
        self.as_user('other')
        self.assertEqual(self.client.get('/tasks').json(), [])
        self.assertEqual(self.client.delete(f"/tasks/{task['id']}").status_code, 404)
        self.as_user('employee')
        self.assertEqual(self.client.delete(f"/tasks/{task['id']}").status_code, 200)

    def test_reminder_uses_utc_and_rejects_bad_dates(self):
        response = self.client.post('/reminders', json={'message':'Meeting','due_date':'2026-10-04T10:00:00+04:00'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/reminders').json()[0]['due_date'], '2026-10-04T06:00:00Z')
        self.assertEqual(self.client.post('/reminders', json={'message':'Bad','due_date':'invalid'}).status_code, 400)

    def test_meeting_proposes_tasks_without_saving(self):
        plan = {'summary':'Budget approved.', 'decisions':['Use existing budget'], 'tasks':[{'title':'Send budget','due_date':None,'source':'meeting'}]}
        with patch('scripts.llm_router.ask_llm', return_value=json.dumps(plan)):
            response = self.client.post('/meetings/analyze', json={'notes':'Budget approved. Alice to send budget.'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['tasks'][0]['title'], 'Send budget')
        self.assertEqual(self.db.query(PersonalTask).count(), 0)
        proposed = response.json()['tasks'][0]
        self.client.post('/tasks', json=proposed)
        self.assertEqual(self.db.query(PersonalTask).count(), 1)

    def test_meeting_invalid_plan_and_path_rejected(self):
        with patch('scripts.llm_router.ask_llm', return_value='not json'):
            self.assertEqual(self.client.post('/meetings/analyze', json={'notes':'Notes'}).status_code, 502)
        self.assertEqual(self.client.post('/meetings/analyze', json={'filename':'../.env'}).status_code, 400)
        self.assertEqual(self.db.query(PersonalTask).count(), 0)

    def test_chat_task_plan_precedes_dataset_routing(self):
        plan = {'summary':'Follow up with HR.', 'decisions':[], 'tasks':[{'title':'Contact HR','due_date':None}]}
        with patch('scripts.llm_router.ask_llm', return_value=json.dumps(plan)), patch('app.main._get_uploaded_data_files') as files:
            response = self.client.post('/query', json={'question':'Create a task to contact HR','file_scope':'selected','selected_files':['data.csv']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'task_plan')
        files.assert_not_called()
        self.assertEqual(self.db.query(PersonalTask).count(), 0)

    def test_chat_ticket_uses_authenticated_owner_on_approval(self):
        row = ApprovalRequest(username='employee',session_id=1,tool_name='create_support_ticket',tool_arguments={'subject':'Error','description':'Help','created_by':'other'},status='pending')
        self.db.add(row)
        self.db.commit()
        from types import SimpleNamespace
        with patch('app.main.init_clients'), patch('app.main.call_tool_on_client', return_value=SimpleNamespace(content=[SimpleNamespace(text='Ticket created')],isError=False)) as call:
            response = self.client.post('/query/approve', json={'session_id':1,'approval_id':row.id,'approved':True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(call.call_args.args[1]['created_by'], 'employee')


class EvidenceTests(unittest.TestCase):
    def test_pdf_chunks_follow_real_pages(self):
        stream = io.BytesIO()
        pdf = canvas.Canvas(stream)
        pdf.drawString(40, 700, 'Annual leave is twenty days.')
        pdf.showPage()
        pdf.drawString(40, 700, 'Report technical issues to IT.')
        pdf.save()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.pdf'
            path.write_bytes(stream.getvalue())
            pages = pdf_pages(str(path))
            self.assertEqual([p[0] for p in pages], [1,2])
            chunks = list(page_chunks(pages, size=15, overlap=2))
            self.assertTrue(all(page in {1,2} for page, text in chunks))
            citation = citation_for('policy.pdf', 'Report technical issues to IT.', {'page':99}, directory)
            self.assertEqual(citation['page'], 2)
            html = citations_html([citation])
            self.assertIn('page 2', html)
            self.assertIn('data-page="2"', html)

    def test_unverified_pages_are_never_claimed(self):
        citation = citation_for('missing.pdf', 'Text', {'page':10}, '/tmp')
        self.assertIsNone(citation['page'])
        self.assertIn('page unavailable', citations_html([citation]))

    def test_numeric_summary_uses_one_measure_not_all_columns(self):
        df = pd.DataFrame({'Year':[2025,2026], 'Sales':['1,000','2,000'], 'Expenses':[500,700]})
        result = explain_dataset(df, 'sales.csv')
        self.assertEqual(result['value_column'], 'Sales')
        self.assertEqual(result['result'], 3000)
        self.assertEqual(result['formula'], 'sum(Sales)')
        self.assertIn('Not specified', result['units'])

    def test_grouped_calculations_and_invalid_rows(self):
        df = pd.DataFrame({'Department':['A','A','B'], 'Revenue':['$10','bad','$20']})
        result = explain_dataset(df, 'sales.csv', 'Revenue', 'Department')
        self.assertEqual(result['rows_excluded'], 1)
        self.assertEqual(result['result'], 30)
        self.assertEqual(result['groups'], [{'group':'B','value':20.0},{'group':'A','value':10.0}])

    def test_mixed_units_withhold_total(self):
        result = explain_dataset(pd.DataFrame({'Value':[10,20], 'Units':['Dollars','Percent']}), 'mixed.csv')
        self.assertIsNone(result['result'])
        self.assertIn('Multiple units', result['warnings'][1])

    def test_execution_details_escape_html(self):
        self.assertIn('&lt;script&gt;', analysis_details_html({'code':'<script>', 'method':'Python'}))

    def test_timezone_conversion(self):
        self.assertEqual(utc_date('2026-10-04T10:00:00'), datetime(2026,10,4,6))


class AnalysisTraceTests(unittest.TestCase):
    def test_generated_analysis_keeps_executed_code(self):
        from app.data_analysis import _single_pass_analysis
        trace = {}
        code = "result = str(df['Sales'].sum())"
        with patch('app.data_analysis.ask_llm', return_value=code), patch('app.data_analysis._exec_safe', return_value={'error':None,'result':'30','chart_base64':None}):
            _single_pass_analysis(pd.DataFrame({'Sales':[10,20]}), 'Sales: int', '10,20', 'Total sales', False, trace=trace)
        self.assertEqual(trace['code'], code)
        self.assertEqual(trace['method'], 'Executed model-generated Python')

    def test_index_metadata_uses_real_pages(self):
        import ast
        import uuid
        from test_file_scope import load_definitions
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'policy.pdf'
            stream = io.BytesIO()
            pdf = canvas.Canvas(stream)
            pdf.drawString(40,700,'Page one policy')
            pdf.showPage()
            pdf.drawString(40,700,'Page two policy')
            pdf.save()
            path.write_bytes(stream.getvalue())
            collection = Mock()
            ns = load_definitions('app/rag.py', {'process_and_store_document'}, {'collection':collection,'uuid':uuid,'get_embedding':Mock(return_value=[0.0,1.0]),'_extract_text_from_pdf':Mock()})
            ns['process_and_store_document'](str(path), 'policy.pdf')
        metadata = collection.add.call_args.kwargs['metadatas']
        self.assertEqual([m['page'] for m in metadata], [1,2])
        self.assertTrue(all(m['page_verified'] for m in metadata))


if __name__ == '__main__':
    unittest.main()
