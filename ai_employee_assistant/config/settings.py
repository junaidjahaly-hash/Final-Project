import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

LOCAL_FAST_MODEL = os.getenv("LOCAL_FAST_MODEL", "qwen3.5:4b")       # Tier 1: Fast conversational, greetings, quick queries
LOCAL_MAIN_MODEL = os.getenv("LOCAL_MAIN_MODEL", "qwen3.5:9b")       # Offline/privacy fallback
CLOUD_MODEL = os.getenv("CLOUD_MODEL", "gemma4:31b-cloud")           # Primary model for meaningful reasoning work
VISION_MODEL = os.getenv("VISION_MODEL", CLOUD_MODEL)
LOCAL_MODEL = os.getenv("LOCAL_MODEL", LOCAL_MAIN_MODEL)             # Backward compatibility fallback
CLOUD_FIRST_FOR_MAIN = os.getenv("CLOUD_FIRST_FOR_MAIN", "true").lower() in {"1", "true", "yes", "on"}
GEMINI_FALLBACK_ENABLED = os.getenv("GEMINI_FALLBACK_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

LLM_CACHE_SIZE = int(os.getenv("LLM_CACHE_SIZE", "128"))
# Keep routine answers concise. Individual callers can request a larger response
# when they genuinely need it (for example, a generated report).
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "400"))
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

# MCP servers are lazy-loaded by intent. Only the internal server is started
# with FastAPI, which keeps startup quick and prevents optional integrations
# from blocking the whole application when npm or the network is unavailable.
MCP_CONNECT_TIMEOUT_SECONDS = float(os.getenv("MCP_CONNECT_TIMEOUT_SECONDS", "8"))
MCP_TOOL_TIMEOUT_SECONDS = float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "25"))
MCP_MAX_ROUTED_TOOLS = int(os.getenv("MCP_MAX_ROUTED_TOOLS", "6"))
MCP_EMBEDDING_MODEL = os.getenv("MCP_EMBEDDING_MODEL", "nomic-embed-text")
MCP_EMBEDDING_TIMEOUT_SECONDS = float(os.getenv("MCP_EMBEDDING_TIMEOUT_SECONDS", "8"))
MCP_SEMANTIC_THRESHOLD = float(os.getenv("MCP_SEMANTIC_THRESHOLD", "0.55"))
MCP_SEMANTIC_MARGIN = float(os.getenv("MCP_SEMANTIC_MARGIN", "0.04"))
MCP_FETCH_ENABLED = os.getenv("MCP_FETCH_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
MCP_TIME_ENABLED = os.getenv("MCP_TIME_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
MCP_LOCAL_TIMEZONE = os.getenv("MCP_LOCAL_TIMEZONE", "Indian/Mauritius")
