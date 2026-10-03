from functools import lru_cache
from html import escape
from pathlib import Path
import re


def pdf_pages(file_path):
    from pypdf import PdfReader
    try:
        return [(number, page.extract_text() or '') for number, page in enumerate(PdfReader(file_path).pages, 1)]
    except Exception:
        return []


def page_chunks(pages, size=1000, overlap=100):
    for page, text in pages:
        for start in range(0, len(text), size - overlap):
            chunk = text[start:start + size].strip()
            if chunk:
                yield page, chunk


@lru_cache(maxsize=64)
def _cached_pages(path, modified):
    return pdf_pages(path)


def citation_for(filename, text, metadata, upload_dir):
    page = metadata.get('page') if metadata.get('page_verified') else None
    if not page and filename:
        path = (Path(upload_dir) / filename).resolve()
        if path.parent == Path(upload_dir).resolve() and path.is_file():
            needle = re.sub(r'\s+', '', text[:160]).lower()
            if needle:
                for number, content in _cached_pages(str(path), path.stat().st_mtime_ns):
                    if needle in re.sub(r'\s+', '', content).lower():
                        page = number
                        break
    return {'filename': filename, 'page': page, 'excerpt': text[:350]}


def citations_html(citations):
    if not citations:
        return ''
    unique = {(c['filename'], c.get('page'), c.get('excerpt', '')): c for c in citations}
    items = []
    for item in unique.values():
        name = escape(item['filename'] or 'Document', quote=True)
        page = item.get('page')
        label = f'{name}, page {page}' if page else f'{name} (page unavailable)'
        items.append(f'<li><button type="button" class="citation-open" data-document="{name}" data-page="{int(page) if page else 1}">{label}</button><blockquote>{escape(item.get("excerpt", ""))}</blockquote></li>')
    return '<details class="evidence-details"><summary>Document evidence · sources consulted</summary><ul>' + ''.join(items) + '</ul></details>'
