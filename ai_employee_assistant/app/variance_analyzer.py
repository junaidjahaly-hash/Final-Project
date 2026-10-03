import io
import math
import base64
import numpy as np
import pandas as pd
from app.data_analysis import _get_plt, _get_cached_df

def sanitize_for_json(obj):
    """Recursively convert numpy types (int64, float64, ndarray) into native Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    elif isinstance(obj, (np.int64, np.int32, np.int16, np.int8, np.integer)):
        return int(obj)
    elif isinstance(obj, (np.float64, np.float32, np.float16, np.floating)):
        return float(obj) if not math.isnan(obj) and not math.isinf(obj) else 0.0
    elif isinstance(obj, np.ndarray):
        return sanitize_for_json(obj.tolist())
    return obj

def run_variance_analysis(file_path_1: str, prev_year: str = None, curr_year: str = None) -> dict:
    """Compare two financial datasets or analyze period-over-period internal variance."""
    plt = _get_plt()
    plt.close('all')

    df1 = _get_cached_df(file_path_1)
    
    # If single dataset, attempt to group by 'year' or 'period' column
    year_cols = [c for c in df1.columns if 'year' in c.lower() or 'period' in c.lower()]
    val_cols = df1.select_dtypes(include=[np.number]).columns.tolist()
    cat_cols = df1.select_dtypes(include=['object']).columns.tolist()

    if not val_cols:
        return {"error": "No numeric metric columns available for variance analysis."}

    val_col = val_cols[0]
    cat_col = cat_cols[0] if cat_cols else df1.columns[0]

    if year_cols:
        year_col = year_cols[0]
        df1['_year_str'] = df1[year_col].astype(str).str.replace('.0', '', regex=False)
        years = sorted(df1['_year_str'].dropna().unique())
        
        if len(years) >= 2:
            # Match requested years or default to last 2 available
            p_yr = str(prev_year) if prev_year and str(prev_year) in years else years[-2]
            c_yr = str(curr_year) if curr_year and str(curr_year) in years else years[-1]
            
            p_data = df1[df1['_year_str'] == p_yr].groupby(cat_col)[val_col].sum()
            c_data = df1[df1['_year_str'] == c_yr].groupby(cat_col)[val_col].sum()

            comp_df = pd.DataFrame({'Previous': p_data, 'Current': c_data}).fillna(0)
            comp_df['Dollar_Variance'] = comp_df['Current'] - comp_df['Previous']
            comp_df['Pct_Change'] = np.where(
                comp_df['Previous'] != 0,
                (comp_df['Dollar_Variance'] / comp_df['Previous']) * 100,
                0.0
            )
            comp_df['Abs_Variance'] = comp_df['Dollar_Variance'].abs()
            
            # Exclude generic "All Industries" row if present to focus on specific sectors
            clean_comp = comp_df[~comp_df.index.astype(str).str.lower().str.contains('all ind')]
            if clean_comp.empty:
                clean_comp = comp_df

            top_df = clean_comp.nlargest(6, 'Abs_Variance')

            max_val_raw = max(top_df['Previous'].max(), top_df['Current'].max())
            if max_val_raw >= 1e9:
                scale_factor = 1e9
                unit_label = "$ Billions"
            elif max_val_raw >= 1e6:
                scale_factor = 1e6
                unit_label = "$ Millions"
            elif max_val_raw >= 1e3:
                scale_factor = 1e3
                unit_label = "$ Thousands"
            else:
                scale_factor = 1.0
                unit_label = "$"

            prev_scaled = top_df['Previous'] / scale_factor
            curr_scaled = top_df['Current'] / scale_factor

            fig, ax = plt.subplots(figsize=(9.5, 4.8))
            fig.patch.set_facecolor('#0f172a'); ax.set_facecolor('#1e293b')

            x = np.arange(len(top_df))
            width = 0.35

            rects1 = ax.bar(x - width/2, prev_scaled, width, label=f'Period {prev_year}', color='#6366f1', alpha=0.9, edgecolor='#818cf8')
            rects2 = ax.bar(x + width/2, curr_scaled, width, label=f'Period {curr_year}', color='#06b6d4', alpha=0.9, edgecolor='#22d3ee')

            for rects in [rects1, rects2]:
                for rect in rects:
                    h = rect.get_height()
                    if h > 0:
                        ax.annotate(f"{h:,.1f}",
                                    xy=(rect.get_x() + rect.get_width() / 2, h),
                                    xytext=(0, 4), textcoords="offset points",
                                    ha='center', va='bottom', color='#cbd5e1',
                                    fontsize=8.5, fontweight='bold')

            for i in range(len(top_df)):
                diff = curr_scaled.iloc[i] - prev_scaled.iloc[i]
                pct = top_df['Pct_Change'].iloc[i]
                peak_h = max(prev_scaled.iloc[i], curr_scaled.iloc[i])
                
                badge_color = '#10b981' if diff >= 0 else '#ef4444'
                arrow = '▲' if diff >= 0 else '▼'
                sign = '+' if diff >= 0 else ''
                
                badge_text = f"{arrow} {sign}{diff:,.1f}\n({sign}{pct:.1f}%)"
                ax.annotate(badge_text,
                            xy=(x[i], peak_h),
                            xytext=(0, 18), textcoords="offset points",
                            ha='center', va='bottom', color=badge_color,
                            fontsize=8, fontweight='bold',
                            bbox=dict(boxstyle="round,pad=0.25", fc="#0f172a", ec=badge_color, lw=1, alpha=0.85))

            ax.set_xlabel('Industry / Sector Category', color='#f8fafc', fontsize=11, fontweight='bold', labelpad=10)
            ax.set_ylabel(f'Total Revenue ({unit_label})', color='#f8fafc', fontsize=11, fontweight='bold')
            ax.set_title(f"Period-over-Period Financial Variance ({p_yr} vs {c_yr})", color='#f8fafc', fontsize=13, fontweight='bold', pad=15)
            ax.set_xticks(x)
            
            labels = [str(lbl)[:16] + "..." if len(str(lbl)) > 16 else str(lbl) for lbl in top_df.index]
            ax.set_xticklabels(labels, color='#f8fafc', rotation=12, ha='right', fontsize=9.5, fontweight='600')
            ax.tick_params(colors='#94a3b8')
            ax.grid(axis='y', linestyle='--', alpha=0.15, color='#94a3b8')
            ax.spines['bottom'].set_color('#334155'); ax.spines['left'].set_color('#334155')
            ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
            ax.legend(facecolor='#0f172a', edgecolor='#334155', labelcolor='#f8fafc', loc='upper right', fontsize=10)

            # Narrow the y-axis range when the values are close together.
            min_val = min(prev_scaled.min(), curr_scaled.min())
            max_val = max(prev_scaled.max(), curr_scaled.max())
            spread = max_val - min_val
            
            if spread > 0 and spread < (max_val * 0.3):
                y_bottom = max(0, min_val - (spread * 1.5))
                y_top = max_val + (spread * 3.5)
            else:
                y_bottom = 0
                y_top = max_val * 1.35

            ax.set_ylim(y_bottom, y_top)

            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=130, bbox_inches='tight', facecolor=fig.get_facecolor())
            buf.seek(0)
            chart_b64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close(fig)

            total_prev = float(comp_df['Previous'].sum())
            total_curr = float(comp_df['Current'].sum())
            total_var = float(total_curr - total_prev)
            total_pct = float((total_var / total_prev * 100)) if total_prev else 0.0

            res = {
                "period_prev": str(p_yr),
                "period_curr": str(c_yr),
                "years_available": [str(y) for y in years],
                "total_prev": round(total_prev / scale_factor, 2),
                "total_curr": round(total_curr / scale_factor, 2),
                "total_variance": round(total_var / scale_factor, 2),
                "total_pct_change": round(total_pct, 2),
                "unit_label": unit_label,
                "chart_base64": chart_b64,
                "top_variances": top_df[['Previous', 'Current', 'Dollar_Variance', 'Pct_Change']].to_dict('index')
            }
            return sanitize_for_json(res)

    return {"error": "Dataset does not contain multiple annual or period timestamps for automatic variance comparison."}
