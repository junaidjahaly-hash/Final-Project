import re
import pandas as pd

PII_COLUMN_KEYWORDS = [
    'ssn', 'social_security', 'credit_card', 'card_num', 'passport',
    'email', 'phone', 'mobile', 'salary', 'compensation', 'dob', 'birth'
]

def scan_and_redact_pii(df: pd.DataFrame) -> tuple:
    """Return a redacted dataframe and a list of the changes made."""
    df_clean = df.copy()
    redactions = []

    for col in df_clean.columns:
        col_lower = col.lower()
        if any(kw in col_lower for kw in PII_COLUMN_KEYWORDS):
            if 'ssn' in col_lower or 'social' in col_lower:
                df_clean[col] = "***-**-XXXX"
                redactions.append(f"Redacted SSN column '{col}'")
            elif 'card' in col_lower or 'credit' in col_lower:
                df_clean[col] = "****-****-****-XXXX"
                redactions.append(f"Redacted Credit Card column '{col}'")
            elif 'email' in col_lower:
                df_clean[col] = "redacted_user@anonymized.com"
                redactions.append(f"Anonymized Email column '{col}'")
            elif 'phone' in col_lower or 'mobile' in col_lower:
                df_clean[col] = "+1 (***) ***-XXXX"
                redactions.append(f"Masked Phone column '{col}'")
            elif 'salary' in col_lower or 'compensation' in col_lower:
                df_clean[col] = "[REDACTED FINANCIAL PII]"
                redactions.append(f"Redacted Compensation column '{col}'")

    return df_clean, redactions
