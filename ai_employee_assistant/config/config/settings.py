import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

CLOUD_MODEL = os.getenv("CLOUD_MODEL", "glm-5.3-flash:cloud")
# Optional local model for heavy reasoning (set to empty string if not used)
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "")

LLM_CACHE_SIZE = int(os.getenv("LLM_CACHE_SIZE", "128"))
