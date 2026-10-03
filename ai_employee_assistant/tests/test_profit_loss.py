import io
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.profit_loss import calculate_profit_loss
from app.pdf_generator import generate_pdf_report
from app.main import app
from app.auth import get_current_user


class ProfitLossTests(unittest.TestCase):
    def test_profit_loss_and_break_even(self):
        for expenses, outcome, expected in [(70, 'Profit', 30), (120, 'Loss', -20), (100, 'Break-even', 0)]:
            result = calculate_profit_loss(pd.DataFrame({'income': [100], 'expense': [expenses]}),
                                           {'revenue_column': 'income', 'expense_column': 'expense'})
            self.assertEqual((result['outcome'], result['profit_loss']), (outcome, expected))

    def test_survey_rows_require_one_period_and_preserve_units(self):
        df = pd.DataFrame({'year': [2024, 2024, 2025, 2025],
                           'variable': ['Total income', 'Total expenditure'] * 2,
                           'value': [100, 80, 120, 130], 'unit': ['DOLLARS(millions)'] * 4})
        request = {'mode': 'rows', 'label_column': 'variable', 'value_column': 'value',
                   'income_label': 'Total income', 'expense_label': 'Total expenditure'}
        with self.assertRaisesRegex(ValueError, 'Filter year'):
            calculate_profit_loss(df, request)
        result = calculate_profit_loss(df, {**request, 'filters': {'year': '2025'}})
        self.assertEqual(result['profit_loss'], -10)
        self.assertEqual(result['units'], 'DOLLARS(millions)')

    def test_missing_expenses_or_mixed_currencies_are_rejected(self):
        for df in [pd.DataFrame({'income': [100], 'expense': ['suppressed']}),
                   pd.DataFrame({'income': [100, 100], 'expense': [10, 10], 'currency': ['USD', 'MUR']})]:
            with self.assertRaises(ValueError):
                calculate_profit_loss(df, {'revenue_column': 'income', 'expense_column': 'expense'})

    def test_api_and_pdf_include_financial_result_without_audit_claim(self):
        app.dependency_overrides[get_current_user] = lambda: {'username': 'employee', 'role': 'employee'}
        try:
            with patch('app.workflows.financial_dataset', return_value=pd.DataFrame({'income': [100], 'expense': [70]})):
                response = TestClient(app).post('/data/profit-loss/example.csv', json={'revenue_column': 'income', 'expense_column': 'expense'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['profit_loss'], 30)
        finally:
            app.dependency_overrides.clear()
        pdf = generate_pdf_report('Financial review', 'Profit: 30\nIncome: 100\nExpenses: 70')
        text = '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn('Profit: 30', text)
        self.assertNotIn('VERIFIED & COMPLIANT', text)
        self.assertIn('No independent audit opinion', text)
