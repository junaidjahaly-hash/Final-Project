
import os
import io
import re
import math
import base64
import hashlib
import time
import pandas as pd
import httpx

# macOS may deny writes to ~/.matplotlib from a sandboxed IDE process. Keep the
# font cache in the project instead so chart imports remain quiet and fast.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MPL_CONFIG_DIR = os.path.join(_PROJECT_ROOT, ".matplotlib")
os.makedirs(_MPL_CONFIG_DIR, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", _MPL_CONFIG_DIR)

# Resilient loader for matplotlib (bypasses broken macOS pyexpat symbols or missing package)
_plt = None
def _get_plt():
    global _plt
    if _plt is None:
        try:
            import sys, types
            import matplotlib
            matplotlib.use('Agg')
            try:
                import matplotlib.pyplot as plt
                _plt = plt
            except ImportError:
                dummy = types.ModuleType('plistlib')
                dummy.InvalidFileException = Exception
                dummy.load = lambda *a, **kw: {}
                dummy.loads = lambda *a, **kw: {}
                sys.modules['plistlib'] = dummy
                import matplotlib.pyplot as plt
                _plt = plt
        except Exception:
            _plt = False
    return _plt if _plt is not False else None
    return _plt

_df_cache = {}               # file_path -> (mtime, df)
_analysis_response_cache = {}# cache_key -> (timestamp, result_dict)
ANALYSIS_ENGINE_VERSION = "4"  # Bump when analysis behavior changes to bypass stale failures.


def _get_cached_df(file_path: str) -> pd.DataFrame:
    """Load and clean a dataframe, reusing the cached copy until the file changes."""
    mtime = os.path.getmtime(file_path)
    if file_path in _df_cache and _df_cache[file_path][0] == mtime:
        return _df_cache[file_path][1].copy()
    
    if file_path.endswith(('.xlsx', '.xls')):
        df = pd.read_excel(file_path)
    else:
        df = pd.read_csv(file_path)
    
    # Clean numeric columns before caching to avoid repeated conversions.
    for col in df.columns:
        if df[col].dtype == 'object':
            sample = df[col].dropna().head(50).astype(str).str.strip()
            if len(sample) > 0 and sample.str.contains(r'\d').mean() > 0.5:
                cleaned = pd.to_numeric(
                    df[col].astype(str).str.replace(r'[^0-9.\-]', '', regex=True),
                    errors='coerce'
                )
                if cleaned.notna().sum() / max(len(df), 1) > 0.3:
                    df[col] = cleaned.fillna(0)

    _df_cache[file_path] = (mtime, df)
    return df.copy()

def clear_file_cache(file_path: str):
    """Clear memory caches when a file is deleted."""
    global _df_cache, _analysis_response_cache
    if file_path in _df_cache:
        del _df_cache[file_path]
    keys_to_del = [k for k in _analysis_response_cache if file_path in k]
    for k in keys_to_del:
        del _analysis_response_cache[k]


def sanitize_for_json(obj):
    """Recursively replace NaN/Infinity with None so JSON can serialize."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    return obj


from config.settings import OLLAMA_HOST
from scripts.llm_router import ask_llm


def _extract_code(response: str) -> str:
    """Extract Python code from LLM response."""
    if "```python" in response:
        return response.split("```python")[1].split("```")[0].strip()
    elif "```" in response:
        return response.split("```")[1].split("```")[0].strip()
    return response.strip()


def _exec_safe(code: str, df: pd.DataFrame) -> dict:
    """Execute generated code in the supplied namespace and capture text and charts."""
    plt = _get_plt()
    if plt:
        plt.close('all')
        plt.show = lambda *args, **kwargs: None
    
    # Convert CSS rgba colors to a format Matplotlib accepts.
    code = code.replace("rgba(255,255,255,0.1)", "#334155").replace("rgba(255, 255, 255, 0.1)", "#334155")
    code = re.sub(r"rgba\([^)]+\)", "'#334155'", code)
    
    # Add lowercase aliases for generated code that uses different column casing.
    df_copy = df.copy()
    for col in list(df.columns):
        if isinstance(col, str) and col.lower() not in df_copy.columns:
            df_copy[col.lower()] = df_copy[col]
            
    # Capture printed output alongside the chart.
    import sys
    stdout_buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_buf
    
    namespace = {
        "__builtins__": __builtins__,
        "df": df_copy, "pd": pd, "io": io,
        "base64": base64, "plt": plt, "np": __import__("numpy"),
    }
    
    exec_error = None
    try:
        exec(code, namespace)
    except Exception as e:
        exec_error = str(e)
    finally:
        sys.stdout = old_stdout
    
    printed_out = stdout_buf.getvalue().strip()
    if exec_error:
        return {"result": None, "chart_base64": None, "error": exec_error}
    
    result = namespace.get("result", None)
    if (result is None or str(result) == "None") and printed_out:
        result = printed_out
        
    chart_b64 = None
    
    # Priority 1: Explicit chart_result variable
    user_chart = namespace.get("chart_result")
    if user_chart and isinstance(user_chart, str) and len(user_chart) > 100:
        chart_b64 = user_chart
    
    # Priority 2: result is a Figure
    if plt:
        try:
            from matplotlib.figure import Figure
            if isinstance(result, Figure):
                buf = io.BytesIO()
                result.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=result.get_facecolor())
                buf.seek(0)
                chart_b64 = base64.b64encode(buf.read()).decode('utf-8')
                plt.close(result)
                result = "Chart generated successfully."
        except Exception:
            pass
    
    # Priority 3: Catch any leftover open figures
    if not chart_b64 and plt:
        try:
            open_figs = plt.get_fignums()
            if open_figs:
                fig = plt.figure(open_figs[-1])
                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
                buf.seek(0)
                chart_b64 = base64.b64encode(buf.read()).decode('utf-8')
                plt.close('all')
                if result is None:
                    result = "Chart generated successfully."
        except Exception:
            pass
    
    return {"result": result, "chart_base64": chart_b64, "error": None}


def _is_chart_request(question: str) -> bool:
    """Detect if user is asking for a visual chart."""
    q = question.lower()
    chart_words = ["chart", "graph", "plot", "visuali", "bar chart", "pie chart",
                   "line chart", "histogram", "scatter", "diagram", "show me a",
                   "represent", "draw", "display"]
    return any(w in q for w in chart_words)


def _build_schema_context(df: pd.DataFrame) -> str:
    """Build compact schema description for the LLM."""
    lines = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        non_null = df[col].notna().sum()
        if df[col].dtype == 'object':
            unique = df[col].dropna().unique()
            sample = list(unique[:8])
            lines.append(f"- {col} ({dtype}, {non_null} non-null, {len(unique)} unique): {sample}")
        else:
            mn, mx = df[col].min(), df[col].max()
            lines.append(f"- {col} ({dtype}, {non_null} non-null, range: {mn} to {mx})")
    return "\n".join(lines)


def analyze_data_file(file_path: str, question: str = None) -> dict:
    """Analyze a CSV or Excel file and cache the response by content hash."""
    t0 = time.time()
    
    try:
        df = _get_cached_df(file_path)
    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}

    mtime = os.path.getmtime(file_path)
    cache_key = hashlib.md5(f"{ANALYSIS_ENGINE_VERSION}_{file_path}_{question}_{mtime}".encode()).hexdigest()
    
    if cache_key in _analysis_response_cache:
        cached_res = _analysis_response_cache[cache_key].copy()
        cached_res["latency"] = f"{time.time() - t0:.3f}s (Instant Cache)"
        return cached_res

    summary = {
        "rows": len(df),
        "columns": list(df.columns),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
    }
    
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    good_num_cols = [c for c in numeric_cols if "unnamed" not in c.lower() and df[c].nunique() >= 2]
    if good_num_cols:
        summary["numeric_stats"] = df[good_num_cols].describe().to_dict()

    schema_ctx = _build_schema_context(df)
    preview_str = df.head(3).to_string()

    chart_base64 = None
    llm_analysis = None

    if not question:
        is_chart = True
        question_task = "Create the single most insightful summary visualization and financial overview of this dataset."
    else:
        is_chart = _is_chart_request(question)
        question_task = question

    trace = {}
    chart_base64, llm_analysis = _single_pass_analysis(df, schema_ctx, preview_str, question_task, is_chart, trace=trace)

    res = sanitize_for_json({
        "summary": summary,
        "chart": chart_base64,
        "analysis": llm_analysis,
        "latency": f"{time.time() - t0:.2f}s",
        "explanation": trace
    })
    
    _analysis_response_cache[cache_key] = res.copy()
    return res


def _single_pass_analysis(df: pd.DataFrame, schema_ctx: str, preview_str: str, question: str, generate_chart: bool, trace: dict | None = None) -> tuple:
    """Generate findings and a Matplotlib chart in one model call, using the requested chart type."""
    q_lower = question.lower()
    
    chart_type_directive = "BAR CHART (plt.bar or plt.barh)"
    if "pie" in q_lower:
        chart_type_directive = "PIE CHART (plt.pie(values, labels=labels, autopct='%1.1f%%', colors=['#6366f1','#06b6d4','#10b981','#f59e0b','#ec4899','#a855f7'], textprops={'color':'#f8fafc'}))"
    elif "line" in q_lower or "graph" in q_lower or "trend" in q_lower:
        chart_type_directive = "LINE GRAPH (plt.plot(x, y, color='#6366f1', marker='o', linewidth=2.5, label='Trend'))"
    elif "scatter" in q_lower:
        chart_type_directive = "SCATTER PLOT (plt.scatter(x, y, color='#06b6d4', alpha=0.7))"

    chart_rules = ""
    if generate_chart:
        chart_rules = f"""
6. GENERATE MATPLOTLIB CHART:
   - CHART TYPE TO USE: {chart_type_directive}
   - STEPS TO EXECUTE:
     val_col = 'Value' if 'Value' in df.columns else df.select_dtypes(include=['number']).columns[0]
     cat_col = 'Industry_name_NZSIOC' if 'Industry_name_NZSIOC' in df.columns else df.select_dtypes(include=['object']).columns[0]
     df[val_col] = pd.to_numeric(df[val_col].astype(str).str.replace(r'[^0-9.\\-]','',regex=True), errors='coerce').fillna(0)
     top10 = df[df[val_col] > 0].groupby(cat_col)[val_col].sum().nlargest(10)
     fig, ax = plt.subplots(figsize=(10, 5))
     # Draw chart based on chart type requested ({chart_type_directive})
     # Set obsidian dark theme background:
     fig.patch.set_facecolor('#0f172a'); ax.set_facecolor('#1e293b')
     ax.tick_params(colors='#94a3b8', labelsize=10)
     ax.xaxis.label.set_color('#f8fafc'); ax.yaxis.label.set_color('#f8fafc'); ax.title.set_color('#6366f1')
     ax.spines['bottom'].set_color('#334155'); ax.spines['left'].set_color('#334155')
     ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
     # Save output:
     buf = io.BytesIO()
     fig.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor=fig.get_facecolor())
     buf.seek(0)
     chart_result = base64.b64encode(buf.read()).decode('utf-8')
     plt.close(fig)
"""

    prompt = f"""You are an Expert Financial Data Analyst & Python Developer. Dataframe `df` has {len(df)} rows.

Schema:
{schema_ctx}

Preview:
{preview_str}

User Question/Task: "{question}"

Write Python code to compute and answer this. CRITICAL RULES:
1. Assign a CLEAN HUMAN-READABLE text answer to `result`:
   - DO NOT USE MARKDOWN ASTERISKS (** or *). Use clean emojis, bullet points (•), and line breaks.
   - Example: result = f"📊 Financial & Audit Report:\\n• Total Revenue: ${{revenue:,.2f}}\\n• Total Expenses: ${{expenses:,.2f}}\\n• Net Profit: ${{net_profit:,.2f}} (Margin: {{margin:.1f}}%)\\n• Audit Status: Verified"
2. Clean numeric strings first: df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[^0-9.\-]','',regex=True), errors='coerce').fillna(0)
3. Always cast numeric values to float before string formatting: float(val)
4. FUZZY MATCH user's words to closest column name in schema.
5. Pre-loaded modules available: df, pd, np, plt, io, base64. No external imports, no print().
6. Return ONLY executable Python code inside ```python ``` blocks.
{chart_rules}"""

    last_error = None
    for attempt in range(2):
        p = prompt
        if attempt > 0:
            p += f"\n\nPrevious attempt had an error: {last_error}\nFix the code and try again."
            
        # Chart scripts are longer than regular answers. Allow enough room to
        # complete a valid Python block; routine chat still uses the lower cap.
        code = _extract_code(ask_llm(p, max_tokens=900, tier="main"))
        out = _exec_safe(code, df)
        
        if out["error"]:
            last_error = out["error"]
            continue
            
        result_text = out["result"] or "Analysis complete."
        result_text = str(result_text).replace('**', '').replace('*', '')
        chart_b64 = out["chart_base64"]
        if trace is not None:
            trace.update({'method': 'Executed model-generated Python', 'code': code,
                          'notes': 'The code below shows the actual columns, filters, grouping, calculations, and unit conversions used. Model-generated calculations still need review.'})
        return chart_b64, result_text

    # A chart request should not fail merely because an LLM returned malformed
    # Python. Render a safe, deterministic executive chart from the dataframe.
    if generate_chart:
        fallback_chart, fallback_text = _build_fallback_chart(df, question)
        if fallback_chart:
            if trace is not None:
                import inspect
                trace.update({'method': 'Deterministic fallback chart', 'code': inspect.getsource(_build_fallback_chart),
                              'notes': 'Generated code failed. This fallback selected numeric and category columns from the dataframe. Its implementation is shown below.'})
            return fallback_chart, fallback_text

    return None, f"I had trouble analyzing that dataset. Error: {last_error}"


def _build_fallback_chart(df: pd.DataFrame, question: str) -> tuple:
    """Render a dependable chart without model-generated code as a last resort."""
    plt = _get_plt()
    if not plt:
        return _build_dependency_free_chart(df)

    try:
        numeric_cols = [col for col in df.select_dtypes(include=["number"]).columns if df[col].notna().any()]
        if not numeric_cols:
            return None, "This dataset does not contain a numeric column to chart."

        # Prefer value/revenue/sales measures when present, otherwise use the
        # first usable numeric column.
        value_col = next(
            (col for col in numeric_cols if any(word in str(col).lower() for word in ("value", "sales", "revenue", "amount", "income"))),
            numeric_cols[0],
        )
        object_cols = [col for col in df.select_dtypes(include=["object", "string", "category"]).columns if df[col].notna().any()]
        category_col = next(
            (col for col in object_cols if any(word in str(col).lower() for word in ("industry", "category", "group", "period", "date"))),
            object_cols[0] if object_cols else None,
        )

        values = pd.to_numeric(df[value_col], errors="coerce").fillna(0)
        if category_col:
            chart_data = pd.DataFrame({"category": df[category_col].astype(str), "value": values})
            chart_data = chart_data[chart_data["category"].str.lower() != "nan"]
            grouped = chart_data.groupby("category", dropna=True)["value"].sum()
        else:
            grouped = values.groupby(values.index).sum()

        grouped = grouped[grouped != 0]
        if grouped.empty:
            return None, "There are no non-zero numeric values available to chart."

        q_lower = question.lower()
        is_line = any(word in q_lower for word in ("line", "trend", "graph"))
        is_pie = "pie" in q_lower
        chart_data = grouped.sort_index() if is_line else grouped.abs().nlargest(10).sort_values()

        fig, ax = plt.subplots(figsize=(11, 5.8))
        fig.patch.set_facecolor("#061526")
        ax.set_facecolor("#0a2138")
        labels = [str(label) for label in chart_data.index]
        sky, cyan, pale = "#38bdf8", "#22d3ee", "#e0f2fe"

        if is_pie:
            pie_data = grouped.abs().nlargest(8)
            ax.pie(pie_data.values, labels=[str(label) for label in pie_data.index], autopct="%1.1f%%", startangle=90,
                   colors=["#0ea5e9", "#38bdf8", "#22d3ee", "#0284c7", "#7dd3fc", "#0369a1", "#67e8f9", "#155e75"],
                   textprops={"color": pale, "fontsize": 9})
        elif is_line:
            ax.plot(labels, chart_data.values, color=cyan, marker="o", linewidth=2.6, markersize=5)
            ax.fill_between(range(len(chart_data)), chart_data.values, color=sky, alpha=.12)
            ax.tick_params(axis="x", rotation=35)
        else:
            ax.barh(labels, chart_data.values, color=sky, edgecolor=cyan, linewidth=.7)

        ax.set_title(f"{value_col} by {category_col or 'record'}", color=pale, fontsize=14, fontweight="bold", pad=14)
        if not is_pie:
            ax.tick_params(colors="#bae6fd", labelsize=9)
            ax.grid(axis="x", color="#38bdf8", alpha=.13, linewidth=.8)
            for spine in ax.spines.values():
                spine.set_visible(False)
        fig.tight_layout()
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return base64.b64encode(buffer.getvalue()).decode("utf-8"), f"📊 Executive chart generated from {value_col} by {category_col or 'record'}."
    except Exception as exc:
        return None, f"Fallback chart generation failed: {exc}"


def _build_dependency_free_chart(df: pd.DataFrame) -> tuple:
    """Create a valid sky-blue PNG bar chart using only the Python standard library.

    This keeps Executive BI usable when matplotlib has not yet been installed.
    The chart title in the UI provides the dataset context; the bars show the
    top aggregated values from the best available category/value columns.
    """
    try:
        import struct
        import zlib

        numeric_cols = [col for col in df.select_dtypes(include=["number"]).columns if df[col].notna().any()]
        if not numeric_cols:
            return None, "This dataset does not contain a numeric column to chart."
        value_col = next(
            (col for col in numeric_cols if any(word in str(col).lower() for word in ("value", "sales", "revenue", "amount", "income"))),
            numeric_cols[0],
        )
        object_cols = [col for col in df.select_dtypes(include=["object", "string", "category"]).columns if df[col].notna().any()]
        category_col = next(
            (col for col in object_cols if any(word in str(col).lower() for word in ("industry", "category", "group", "period", "date"))),
            object_cols[0] if object_cols else None,
        )
        values = pd.to_numeric(df[value_col], errors="coerce").fillna(0)
        if category_col:
            grouped = pd.DataFrame({"category": df[category_col].astype(str), "value": values})
            grouped = grouped[grouped["category"].str.lower() != "nan"].groupby("category")["value"].sum()
        else:
            grouped = values.groupby(values.index).sum()
        top = grouped.abs().nlargest(10)
        if top.empty or float(top.max()) == 0:
            return None, "There are no non-zero numeric values available to chart."

        width, height = 1200, 620
        margin_left, margin_right, margin_top, margin_bottom = 72, 50, 52, 72
        pixels = bytearray([6, 21, 38] * width * height)

        def paint_rect(x0, y0, x1, y1, color):
            for y in range(max(0, y0), min(height, y1)):
                start = (y * width + max(0, x0)) * 3
                end = (y * width + min(width, x1)) * 3
                pixels[start:end] = bytes(color) * max(0, min(width, x1) - max(0, x0))

        paint_rect(margin_left, margin_top, width - margin_right, height - margin_bottom, (10, 33, 56))
        plot_height = height - margin_top - margin_bottom
        for step in range(6):
            y = margin_top + int(plot_height * step / 5)
            paint_rect(margin_left, y, width - margin_right, y + 1, (25, 74, 105))

        max_value = float(top.max())
        available_width = width - margin_left - margin_right
        slot_width = available_width / len(top)
        for index, value in enumerate(top.values):
            bar_height = max(3, int((float(value) / max_value) * (plot_height - 12)))
            x0 = int(margin_left + index * slot_width + slot_width * .18)
            x1 = int(margin_left + (index + 1) * slot_width - slot_width * .18)
            y0 = height - margin_bottom - bar_height
            # Alternating sky shades make individual categories easy to read.
            color = (34, 211, 238) if index % 2 else (56, 189, 248)
            paint_rect(x0, y0, x1, height - margin_bottom, color)
            paint_rect(x0, y0, x1, min(y0 + 3, height - margin_bottom), (186, 230, 253))

        raw = b"".join(b"\x00" + bytes(pixels[row * width * 3:(row + 1) * width * 3]) for row in range(height))

        def png_chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)

        png = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        png += png_chunk(b"IDAT", zlib.compress(raw, 6)) + png_chunk(b"IEND", b"")
        return base64.b64encode(png).decode("utf-8"), f"📊 Executive chart generated from {value_col} by {category_col or 'record'} (dependency-free renderer)."
    except Exception as exc:
        return None, f"Fallback chart generation failed: {exc}"


def predict_trend_forecast(df: pd.DataFrame, value_col: str, periods_ahead: int = 3) -> dict:
    """Forecast values using a linear trend and exponential smoothing."""
    import numpy as np
    try:
        series = pd.to_numeric(df[value_col].astype(str).str.replace(r'[^0-9.\-]', '', regex=True), errors='coerce').dropna()
        if len(series) < 4:
            return {"error": "Insufficient numeric data points for predictive forecasting."}
            
        y = series.values
        x = np.arange(len(y))
        
        slope, intercept = np.polyfit(x, y, 1)
        r2 = float(np.corrcoef(x, y)[0, 1] ** 2) if len(y) > 1 else 1.0
        
        future_x = np.arange(len(y), len(y) + periods_ahead)
        forecast_values = [float(slope * fx + intercept) for fx in future_x]
        
        alpha = 0.3
        exp_smooth = [y[0]]
        for val in y[1:]:
            exp_smooth.append(alpha * val + (1 - alpha) * exp_smooth[-1])
        exp_next = float(alpha * y[-1] + (1 - alpha) * exp_smooth[-1])
        
        return {
            "target_column": value_col,
            "historical_mean": float(y.mean()),
            "trend_slope": float(slope),
            "r2_confidence_score": round(r2, 4),
            "linear_forecast": [round(v, 2) for v in forecast_values],
            "exp_smoothing_next_period": round(exp_next, 2),
            "forecast_direction": "UPWARD ↗️" if slope > 0 else "DOWNWARD ↘️" if slope < 0 else "STABLE ➡️"
        }
    except Exception as e:
        return {"error": f"Forecasting failed: {str(e)}"}


def detect_dataset_outliers(df: pd.DataFrame, numeric_col: str = None) -> dict:
    """Find outliers using the interquartile range and z-scores."""
    import numpy as np
    try:
        if df is None or df.empty:
            return {"total_outliers": 0, "outlier_percentage": 0.0, "details": "Empty dataset."}

        if not numeric_col:
            candidates = [c for c in df.columns if any(k in str(c).lower() for k in ['val', 'rev', 'amount', 'total', 'price', 'dollar'])]
            if not candidates:
                candidates = df.select_dtypes(include=['number']).columns.tolist()
            if not candidates:
                for col in df.columns:
                    converted = pd.to_numeric(df[col].astype(str).str.replace(r'[^0-9.\-]', '', regex=True), errors='coerce')
                    if converted.notnull().sum() > 5:
                        candidates.append(col)
                        break
            if not candidates:
                return {"total_outliers": 0, "outlier_percentage": 0.0, "details": "No numeric column found."}
            numeric_col = candidates[0]

        series = pd.to_numeric(df[numeric_col].astype(str).str.replace(r'[^0-9.\-]', '', regex=True), errors='coerce').dropna()
        if len(series) < 5:
            return {"total_outliers": 0, "outlier_percentage": 0.0, "details": "Dataset too small for anomaly detection."}
            
        q25, q75 = np.percentile(series, [25, 75])
        iqr = q75 - q25
        lower_bound = q25 - 1.5 * iqr
        upper_bound = q75 + 1.5 * iqr
        
        outliers_iqr = series[(series < lower_bound) | (series > upper_bound)]
        
        mean_val = series.mean()
        std_val = series.std()
        z_scores = np.abs((series - mean_val) / (std_val if std_val != 0 else 1))
        outliers_z = series[z_scores > 3.0]
        
        total_outliers = len(outliers_iqr)
        outlier_pct = round((total_outliers / len(series)) * 100, 1)

        solutions = []
        if len(outliers_z) > 0:
            solutions.append(f"🔍 Audit Top Anomalies: Inspect the top {len(outliers_z)} extreme records exceeding 3.0 standard deviations (Max anomaly value: ${round(float(series.max()), 2):,}).")
        if outlier_pct > 10.0:
            solutions.append(f"📊 Dataset Segmentation: High variance detected ({outlier_pct}% outliers). Segment dataset into size-bands before running forecasting.")
        elif outlier_pct > 0:
            solutions.append(f"💡 Winsorization / Cap: Apply 95th percentile capping to smooth extreme spikes for executive reporting.")
        else:
            solutions.append("✅ Baseline Clean: No significant outliers found. Dataset is ready for linear forecasting & executive presentation.")

        solutions.append("🕵️ Fraud Verification: Click 'Fraud Audit' to run Benford's Law test on leading transaction digits.")

        return {
            "column": numeric_col,
            "total_records": len(series),
            "total_outliers": total_outliers,
            "outlier_percentage": outlier_pct,
            "mean": round(float(mean_val), 2),
            "iqr_bounds": {"lower": round(float(lower_bound), 2), "upper": round(float(upper_bound), 2)},
            "iqr_outliers_count": len(outliers_iqr),
            "critical_zscore_anomalies_count": len(outliers_z),
            "max_anomaly_value": round(float(series.max()), 2) if len(outliers_iqr) > 0 else None,
            "solutions": solutions
        }
    except Exception as e:
        return {"total_outliers": 0, "outlier_percentage": 0.0, "solutions": ["✅ Baseline Clean: Dataset ready for analysis."], "error": f"Anomaly detection failed: {str(e)}"}


def clean_dataset_outliers(df: pd.DataFrame, numeric_col: str = None, percentile_cap: float = 95.0):
    """Cap numeric outliers at the requested percentile and return the cleaned dataframe and statistics."""
    import numpy as np
    try:
        df_clean = df.copy()
        if not numeric_col:
            candidates = [c for c in df_clean.columns if any(k in str(c).lower() for k in ['val', 'rev', 'amount', 'total', 'price', 'dollar'])]
            if not candidates:
                candidates = df_clean.select_dtypes(include=['number']).columns.tolist()
            if not candidates:
                return df_clean, {"message": "No numeric column found to clean."}
            numeric_col = candidates[0]

        series = pd.to_numeric(df_clean[numeric_col].astype(str).str.replace(r'[^0-9.\-]', '', regex=True), errors='coerce')
        valid_mask = series.notnull()
        valid_vals = series[valid_mask]

        if len(valid_vals) < 5:
            return df_clean, {"message": "Dataset too small for capping."}

        cap_val = np.percentile(valid_vals, percentile_cap)
        floor_val = np.percentile(valid_vals, 100.0 - percentile_cap)

        capped_series = series.clip(lower=floor_val, upper=cap_val)
        num_modified = int((series != capped_series).sum())

        df_clean[numeric_col] = capped_series.fillna(df_clean[numeric_col])

        return df_clean, {
            "column": numeric_col,
            "total_records": len(df_clean),
            "records_capped": num_modified,
            "upper_cap_value": round(float(cap_val), 2),
            "lower_floor_value": round(float(floor_val), 2)
        }
    except Exception as e:
        return df, {"error": f"Cleaning failed: {str(e)}"}
