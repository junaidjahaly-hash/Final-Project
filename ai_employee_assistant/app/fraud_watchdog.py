import math
import io
import base64
import numpy as np
import pandas as pd
from app.data_analysis import _get_plt, _get_cached_df

def run_benford_fraud_audit(file_path: str) -> dict:
    """Compare leading transaction digits with the expected Benford distribution."""
    plt = _get_plt()
    plt.close('all')

    df = _get_cached_df(file_path)
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    
    if not numeric_cols:
        for col in df.columns:
            cleaned = pd.to_numeric(df[col].astype(str).str.replace(r'[^0-9.\-]', '', regex=True), errors='coerce')
            if cleaned.notna().sum() > 10:
                df[col] = cleaned
                numeric_cols.append(col)

    if not numeric_cols:
        return {"error": "No suitable numeric transaction columns found in dataset for Benford's Law Audit."}

    # Pick the best numeric column (highest number of unique values)
    best_col = max(numeric_cols, key=lambda c: df[c].nunique())
    vals = df[best_col].dropna()
    vals = vals[vals > 0] # Benford's Law applies to positive non-zero numbers

    if len(vals) < 20:
        return {"error": f"Column '{best_col}' has fewer than 20 positive numeric records required for statistical audit."}

    first_digits = vals.astype(str).str.replace(r'[^0-9]', '', regex=True).str.lstrip('0').str[0]
    first_digits = pd.to_numeric(first_digits, errors='coerce').dropna().astype(int)
    first_digits = first_digits[(first_digits >= 1) & (first_digits <= 9)]

    total_count = len(first_digits)
    if total_count == 0:
        return {"error": "Could not extract valid first digits."}

    counts = first_digits.value_counts().reindex(range(1, 10), fill_value=0)
    observed_pct = (counts / total_count).to_dict()

    # Theoretical Benford Distribution: P(d) = log10(1 + 1/d)
    expected_pct = {d: math.log10(1.0 + 1.0 / d) for d in range(1, 10)}

    mad = sum(abs(observed_pct[d] - expected_pct[d]) for d in range(1, 10)) / 9.0

    if mad < 0.006:
        risk_level = "Low Risk (Normal Distribution)"
        status_color = "#10b981" # Green
        verdict = "Dataset strictly complies with Benford's Law distribution. Low risk of manual intervention."
    elif mad < 0.012:
        risk_level = "Medium Risk (Minor Anomaly)"
        status_color = "#f59e0b" # Yellow
        verdict = "Slight deviation from expected distribution. Minor audit review recommended."
    else:
        risk_level = "HIGH RISK (Potential Manipulation)"
        status_color = "#ef4444" # Red
        verdict = "Significant statistical deviation detected! Possible duplicate invoices, rounded numbers, or manual fraud."

    fig, ax = plt.subplots(figsize=(9, 4.5))
    fig.patch.set_facecolor('#0f172a'); ax.set_facecolor('#1e293b')

    digits = list(range(1, 10))
    obs_vals = [observed_pct[d] * 100 for d in digits]
    exp_vals = [expected_pct[d] * 100 for d in digits]

    bar_width = 0.35
    x = np.arange(len(digits))

    ax.bar(x - bar_width/2, obs_vals, bar_width, label='Observed Audit Data', color='#6366f1', alpha=0.85)
    ax.plot(x + bar_width/2, exp_vals, color='#06b6d4', marker='o', linewidth=2.5, label="Benford's Law Curve")

    ax.set_xlabel('First Leading Digit (1-9)', color='#f8fafc', fontsize=11)
    ax.set_ylabel('Percentage (%)', color='#f8fafc', fontsize=11)
    ax.set_title(f"Forensic Audit: Benford's Law Distribution on '{best_col}'", color='#f8fafc', fontsize=13, pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels([str(d) for d in digits], color='#94a3b8')
    ax.tick_params(colors='#94a3b8')
    ax.spines['bottom'].set_color('#334155'); ax.spines['left'].set_color('#334155')
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.legend(facecolor='#1e293b', edgecolor='#334155', labelcolor='#f8fafc')

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
    buf.seek(0)
    chart_b64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)

    z_scores_per_digit = {}
    anomalous_digits = []
    for d in range(1, 10):
        p_exp = expected_pct[d]
        p_obs = observed_pct[d]
        sigma = math.sqrt((p_exp * (1.0 - p_exp)) / max(total_count, 1))
        z_score = (abs(p_obs - p_exp)) / (sigma if sigma > 0 else 1.0)
        z_scores_per_digit[d] = round(z_score, 2)
        if z_score > 2.57:  # 99% Confidence level cutoff
            anomalous_digits.append(d)

    return {
        "column_audited": best_col,
        "records_audited": total_count,
        "mad_score": round(mad, 5),
        "risk_level": risk_level,
        "status_color": status_color,
        "verdict": verdict,
        "anomalous_digits": anomalous_digits,
        "digit_z_scores": z_scores_per_digit,
        "chart_base64": chart_b64,
        "observed_pct": {d: round(v * 100, 2) for d, v in observed_pct.items()},
        "expected_pct": {d: round(v * 100, 2) for d, v in expected_pct.items()}
    }
