from fastapi import FastAPI, Request, HTTPException
import os
import sqlite3
import secrets
import logging
import json
import ollama

# ----------------------
# Logging Setup
# ----------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ----------------------
# Configuration
# ----------------------
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")

# Configure Ollama libray to use Ollama Cloud
ollama.set_api_key(OLLAMA_API_KEY)

app = FastAPI()

# ----------------------
# Session / Memory Setup
# ----------------------
DB_PATH = "/tmp/sessions.db"  # Ephemeral storage on Cloud Run


class SessionManager:
    """Handles ephemeral session memory using SQLite."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    messages TEXT
                )
            """)
        logger.info("Database initialized successfully")

    def get_messages(self, session_id: str, limit: int = 20):
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT messages FROM sessions WHERE session_id = ?",
                (session_id,)
            ).fetchone()
            if row and row["messages"]:
                messages = json.loads(row["messages"])
                logger.info(f"Loaded {len(messages)} messages for session {session_id}")
                return messages[-limit:]
            logger.info(f"No existing messages for session {session_id}")
            return []

    def save_message(self, session_id: str, role: str, text: str):
        messages = self.get_messages(session_id)
        messages.append({"role": role, "text": text})
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO sessions(session_id, messages) VALUES (?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET messages=?",
                (session_id, json.dumps(messages), json.dumps(messages))
            )
        logger.info(f"Saved {role} message for session {session_id}")


session_manager = SessionManager()
