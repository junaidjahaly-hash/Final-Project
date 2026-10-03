from html import escape
import math
import re

import pandas as pd


def numeric_values(series):
    cleaned = series.astype(str).str.replace(',', '', regex=False).str.replace(r'^\s*(?:[$€£]|USD\s*|MUR\s*)', '', regex=True)
    return pd.to_numeric(cleaned, errors='coerce').replace([float('inf'), -float('inf')], float('nan'))


def explain_dataset(df, filename, value_column=None, group_column=None, operation='sum'):
    candidates = [c for c in df.columns if numeric_values(df[c]).notna().any() and not re.search(r'(^id$|_id$|^year$|^index$|unnamed)', str(c), re.I)]
    if value_column is None:
        value_column = next((c for c in candidates if re.search(r'revenue|sales|amount|value|total|price', str(c), re.I)), candidates[0] if candidates else None)
    if value_column not in candidates:
        raise ValueError('Choose a column containing numeric values.')
    if group_column and group_column not in df.columns:
        raise ValueError('Choose an existing grouping column.')
    if operation not in {'sum', 'mean', 'count', 'min', 'max'}:
        raise ValueError('Choose sum, mean, count, min, or max.')
    values = numeric_values(df[value_column])
    valid = values.dropna()
    unit_columns = [c for c in df.columns if str(c).lower() in {'unit', 'units', 'currency'}]
    units = {str(value) for col in unit_columns for value in df.loc[values.notna(), col].dropna().unique()}
    warnings = ['No filters or deduplication applied. Check overlapping categories and reporting periods before interpreting totals.']
    if len(units) > 1:
        warnings.append('Multiple units/currencies are present. A combined numeric total is withheld; filter to one unit first.')
    unit = ', '.join(sorted(units)) if units else 'Not specified in a units/currency column; original numeric scale retained.'
    result = None if len(units) > 1 else float(getattr(valid, operation)()) if len(valid) else None
    if result is not None and not math.isfinite(result):
        result = None
    groups = []
    if group_column and len(units) <= 1:
        frame = pd.DataFrame({'group': df[group_column].fillna('(missing)').astype(str), 'value': values}).dropna(subset=['value'])
        grouped = frame.groupby('group')['value'].agg(operation).sort_values(ascending=False).head(20)
        groups = [{'group': str(key), 'value': float(value)} for key, value in grouped.items()]
    return {'filename': filename, 'rows': len(df), 'rows_used': len(valid), 'rows_excluded': len(df) - len(valid),
            'columns': list(map(str, df.columns)), 'numeric_columns': list(map(str, candidates)), 'value_column': str(value_column),
            'group_column': group_column, 'operation': operation, 'filters': 'None (all rows)',
            'formula': f'{operation}({value_column})' + (f' grouped by {group_column}' if group_column else ''),
            'units': unit, 'result': result, 'groups': groups, 'warnings': warnings,
            'numeric_cleaning': 'Remove commas and leading currency labels; exclude missing, nonnumeric, and infinite values.'}


def analysis_details_html(trace):
    if not trace:
        return ''
    method = escape(trace.get('method', 'Model-generated analysis'))
    code = escape(trace.get('code', ''))
    notes = escape(trace.get('notes', 'Review the executed code for the columns, filters, aggregation, and unit conversions used.'))
    return f'<details class="evidence-details"><summary>How this analysis was produced</summary><p>{method}</p><p>{notes}</p>' + (f'<pre>{code}</pre>' if code else '') + '</details>'
