"""JSM Wiki System Configuration.

Loads all settings from .env file and defines path constants.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

OBSIDIAN_API_KEY = os.getenv("OBSIDIAN_API_KEY", "")
OBSIDIAN_API_URL = "https://127.0.0.1:27124/vault"

OBSIDIAN_VAULT_PATH = Path(os.getenv("OBSIDIAN_VAULT_PATH", str(Path.home() / "Desktop" / "jsm obsidian")))
VAULT_FOLDER = "jsm personal agents (obsidian files)/Agents"

WIKI_PATH = f"{VAULT_FOLDER}/2_Wiki"
SOURCES_PATH = f"{VAULT_FOLDER}/1_Sources"
DAILY_LOG_PATH = f"{VAULT_FOLDER}/3_Logs/daily"
DECISIONS_PATH = f"{VAULT_FOLDER}/3_Logs/decisions"

DATA_DIR = BASE_DIR / "data"
CALENDAR_FILE = DATA_DIR / "calendar.json"

# Google Calendar API
GOOGLE_CREDENTIALS_FILE = BASE_DIR / "credentials.json"
GOOGLE_TOKEN_FILE = DATA_DIR / "google_token.pickle"
GOOGLE_SYNC_STATE_FILE = DATA_DIR / "google_sync_state.json"
GOOGLE_CALENDAR_ENABLED = os.getenv("GOOGLE_CALENDAR_ENABLED", "true").lower() == "true"
GOOGLE_CALENDAR_SYNC_DAYS = int(os.getenv("GOOGLE_CALENDAR_SYNC_DAYS", "90"))

ONTOLOGY_PATH = BASE_DIR / "ontology"
RAW_PATH = BASE_DIR / "raw"
SUBJECT_TREE_FILE = ONTOLOGY_PATH / "subject-tree.md"
TOPICS_FILE = ONTOLOGY_PATH / "topics.md"
MANIFEST_FILE = ONTOLOGY_PATH / "wiki-manifest.json"
DEPENDENCIES_FILE = ONTOLOGY_PATH / "wiki-dependencies.json"

MODEL_PRO = "deepseek-reasoner"
MODEL_FAST = "deepseek-chat"
MODEL_VISION = "gemini-2.5-flash"

WIKI_SCHEMA_FILE = BASE_DIR / "wiki_schema.md"
CONVENTIONS_FILE = BASE_DIR / "CONVENTIONS.md"

MEMO_KEYWORDS = ["고쳐", "노트", "적어놔", "기록해놔", "비판적으로", "메모", "저장", "기억", "써놔", "남겨"]


def validate() -> list[str]:
    """Check required configuration. Returns list of missing items."""
    missing = []
    if not DEEPSEEK_API_KEY:
        missing.append("DEEPSEEK_API_KEY")
    if not OBSIDIAN_API_KEY:
        missing.append("OBSIDIAN_API_KEY")
    if not OBSIDIAN_VAULT_PATH.exists():
        missing.append(f"OBSIDIAN_VAULT_PATH ({OBSIDIAN_VAULT_PATH}) does not exist")
    return missing
