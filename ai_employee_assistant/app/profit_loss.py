"""User-scoped financial calculations from identified income and expense data."""
import math
import re

from app.analysis_evidence import numeric_values


def profit_loss_options(df):
    columns = list(map(str, df.columns))
    numeric = [c for c in columns if numeric_values(df[c]).notna().any()
               and not re.search(r'unnamed|(^id$|_id$)', c, re.I)]
    categories = {c: list(map(str, df[c].dropna().unique())) for c in columns
                  if not re.search('unnamed', c, re.I) and 0 < df[c].nunique() <= 200}
    return {'columns': columns, 'numeric_columns': numeric, 'categories': categories}


def calculate_profit_loss(df, request):
    frame = df.copy()
    filters = request.get('filters', {})
    for column, value in filters.items():
        if column not in frame.columns:
            raise ValueError('Choose existing filter columns.')
        frame = frame[frame[column].astype(str) == str(value)]
    if frame.empty:
        raise ValueError('No rows match this reporting scope.')
    mode = request.get('mode', 'columns')
    if mode == 'rows':
        label, value = request.get('label_column'), request.get('value_column')
        if label not in frame.columns or value not in frame.columns or label == value:
            raise ValueError('Choose separate financial label and amount columns.')
        income_label, expense_label = request.get('income_label'), request.get('expense_label')
        if not income_label or not expense_label or income_label == expense_label:
            raise ValueError('Choose distinct income and expenditure labels.')
        income = frame[frame[label].astype(str) == income_label]
        expense = frame[frame[label].astype(str) == expense_label]
        selected = frame[frame[label].astype(str).isin([income_label, expense_label])]
        excluded = {label, value}
        formula = f'sum({value} where {label} = {income_label}) - sum({value} where {label} = {expense_label})'
        revenue_values, expense_values = income[value], expense[value]
    elif mode == 'columns':
        revenue, expense = request.get('revenue_column'), request.get('expense_column')
        if revenue not in frame.columns or expense not in frame.columns or revenue == expense:
            raise ValueError('Choose separate revenue and total expense columns.')
        selected = frame
        excluded = {revenue, expense}
        revenue_values, expense_values = frame[revenue], frame[expense]
        formula = f'sum({revenue}) - sum({expense})'
    else:
        raise ValueError('Choose columns or labelled rows.')
    for column in selected.columns:
        if re.search(r'(^year$|period|industry|size.*gr|rme_size|currency|^units?$)', str(column), re.I) and column not in excluded:
            if selected[column].dropna().astype(str).nunique() > 1:
                raise ValueError(f'Filter {column} to a single value to avoid mixing periods, categories or units.')
    numbers = [numeric_values(values) for values in (revenue_values, expense_values)]
    if any(values.empty or values.isna().any() for values in numbers):
        raise ValueError('Income and expenditure must contain complete numeric amounts; missing or suppressed figures cannot be assumed zero.')
    if (numbers[1] < 0).any():
        raise ValueError('Use expenditure as positive costs. Signed accounting entries need normalization before this calculation.')
    revenue, expense = [float(values.sum()) for values in numbers]
    result = revenue - expense
    if not all(math.isfinite(value) for value in (revenue, expense, result)):
        raise ValueError('Amounts exceed the supported numeric range.')
    units = [str(v) for c in selected.columns if str(c).lower() in {'unit', 'units', 'currency'}
             for v in selected[c].dropna().unique()]
    return {'revenue': revenue, 'expenses': expense, 'profit_loss': result,
            'outcome': 'Profit' if result > 0 else 'Loss' if result < 0 else 'Break-even',
            'margin_percent': result / revenue * 100 if revenue > 0 else None,
            'units': ', '.join(sorted(set(units))) or 'Original dataset units (not specified)',
            'formula': formula, 'filters': filters, 'rows_used': len(selected),
            'note': 'Based on selected income and expense measures. Not an audit opinion. Confirm that expenses are complete and records do not overlap; tax is included only if present in the selected expenses.'}
