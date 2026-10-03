"""Local semantic retrieval for MCP capabilities, independent of document indexes."""
import asyncio
from collections import OrderedDict
import math
import time

import httpx
from config import settings

SERVER_DESCRIPTIONS = {
    "internal": "Employee assistance: consult company policies, submit helpdesk problems, check support requests, compose or send correspondence, query business records.",
    "filesystem": "Manage uploaded files: locate a document, inspect folders, read contents, rename, move or edit a file.",
    "memory": "Remember personal preferences and facts for later, recall previously saved information, forget remembered details.",
    "fetch": "Read public websites and retrieve information from internet links, articles and online sources.",
    "time": "Find the current local clock or date and convert meeting hours between different time zones.",
}

TOOL_EXAMPLES = {
    "send_email": "Let a colleague know I cannot attend. Contact Sarah about the meeting. Send correspondence.",
    "create_support_ticket": "I need someone from IT to look into my broken laptop. Report a problem to the helpdesk.",
    "get_open_tickets": "How is my reported problem progressing? Check outstanding support requests.",
    "search_company_knowledge": "What are the rules for taking leave? Consult the employee handbook.",
    "search_nodes": "What did I previously tell you about my preferences? Recall saved facts.",
    "create_entities": "Keep in mind that I prefer short responses. Save a fact for later.",
}

_cache = OrderedDict()
_lock = asyncio.Lock()
_retry_after = 0.0


async def similarities(question, descriptions):
    """Return cosine scores, or None when real embeddings are unavailable."""
    global _retry_after
    if not descriptions or time.monotonic() < _retry_after:
        return None
    model = settings.MCP_EMBEDDING_MODEL
    texts = ["search_query: " + question[:6000]] + [
        "search_document: " + description[:6000] for description in descriptions
    ]
    async with _lock:
        if time.monotonic() < _retry_after:
            return None
        missing = list(dict.fromkeys(text for text in texts if (model, text) not in _cache))
        try:
            if missing:
                async with httpx.AsyncClient(timeout=settings.MCP_EMBEDDING_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        settings.OLLAMA_HOST.rstrip("/") + "/api/embed",
                        json={"model": model, "input": missing, "keep_alive": "10m"},
                    )
                    response.raise_for_status()
                    vectors = response.json()["embeddings"]
                if len(vectors) != len(missing):
                    raise ValueError("Incomplete embedding response")
                normalized = []
                for vector in vectors:
                    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
                    if not norm or not math.isfinite(norm):
                        raise ValueError("Invalid embedding vector")
                    normalized.append(tuple(float(value) / norm for value in vector))
                for text, vector in zip(missing, normalized):
                    _cache[(model, text)] = vector
            query = _cache[(model, texts[0])]
            documents = [_cache[(model, text)] for text in texts[1:]]
            if any(len(vector) != len(query) for vector in documents):
                raise ValueError("Embedding dimensions changed")
            scores = [sum(a * b for a, b in zip(query, vector)) for vector in documents]
            for text in texts:
                _cache.move_to_end((model, text))
            while len(_cache) > 512:
                _cache.popitem(last=False)
            return scores
        except (httpx.HTTPError, KeyError, TypeError, ValueError, OverflowError):
            _cache.clear()
            _retry_after = time.monotonic() + 60
            return None


def clarification(tools):
    """Only competing semantic matches without clear wording need clarification."""
    if len(tools) < 2 or any(tool.get("lexical_score", 0) >= 8 for tool in tools):
        return None
    first, second = tools[:2]
    if "semantic_score" not in first or "semantic_score" not in second:
        return None
    if first["semantic_score"] - second["semantic_score"] >= settings.MCP_SEMANTIC_MARGIN:
        return None
    labels = [tool.get("raw_name", tool["name"]).replace("_", " ") for tool in tools[:3]]
    return "Could you clarify what you want me to do: " + ", or ".join(labels) + "?"
