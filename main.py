from fastapi import FastAPI, Request, HTTPException
import os
import sqlite3
import secrets
import logging
import json
from ollama import Client

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
if not OLLAMA_API_KEY:
    logger.warning("OLLAMA_API_KEY not set - Ollama calls may fail")

# Configure Ollama client to use Ollama Cloud
ollama_client = Client(
    host='https://ollama.com',
    headers={'Authorization': f'Bearer {OLLAMA_API_KEY}'}
)


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



# ----------------------
# Chat with Ollama
# ----------------------
async def chat_with_ollama(session_id: str, user_message: str) -> str:
    """Chat with Ollama Cloud using session memory."""
    logger.info(f"Running Ollama chat for session {session_id}")
    logger.info(f"User message: {user_message}")
    
    # Load conversation history
    memory = session_manager.get_messages(session_id)
    
    # Build messages array for Ollama
    messages = []
    
    # Add system instruction
    messages.append({
        "role": "system",
        "content": (
            "You are nifty-bot, a friendly AI agent inspired by the White Rabbit from "
            "Alice in Wonderland. You adore rabbit-themed NFTs on Ethereum L1 and L2. "
            "You often worry about the time. Be short, conversational, and rabbit-themed."
        )
    })
    
    # Add conversation history
    for msg in memory:
        messages.append({
            "role": msg["role"],
            "content": msg["text"]
        })
    
    # Add new user message
    messages.append({
        "role": "user",
        "content": user_message
    })
    
    logger.info(f"Total messages in context: {len(messages)}")
    
    try:
        # Call Ollama Cloud
        response = ollama_client.chat(
            model="gemini-3-pro-preview:latest",
            messages=messages
        )
        
        # Extract reply
        reply = response['message']['content']
        
        logger.info(f"Ollama response: {reply}")
        return reply
        
    except Exception as e:
        logger.exception(f"Error calling Ollama: {e}")
        raise



# ----------------------
# Routes
# ----------------------
@app.post("/chat")
async def chat(request: Request):
    """
    Chat endpoint for nifty-bot-v3.
    
    Expects JSON:
    {
        "session_id": "optional-session-id",
        "message": "user message"
    }
    
    Returns JSON:
    {
        "response": "bot response",
        "session_id": "session-id"
    }
    """
    try:
        data = await request.json()
        session_id = data.get("session_id")
        message = data.get("message", "").strip()

        logger.info(f"Received chat request - session_id: {session_id}, message: {message}")

        # Validate message
        if not message:
            logger.warning("Empty message received")
            raise HTTPException(status_code=400, detail="message required")

        # Generate session_id if first request
        if not session_id:
            session_id = secrets.token_urlsafe(32)
            logger.info(f"Generated new session_id: {session_id}")

        # Chat with Ollama
        try:
            reply = await chat_with_ollama(session_id, message)
            logger.info(f"Ollama returned reply: {reply}")
        except Exception as ollama_error:
            logger.exception(f"Ollama chat failed: {ollama_error}")
            return {
                "response": "Sorry, I encountered an error. Please try again!",
                "session_id": session_id
            }

        # Save messages to SQLite
        session_manager.save_message(session_id, "user", message)
        session_manager.save_message(session_id, "assistant", reply)

        logger.info(f"Sending response: {reply}")
        return {"response": reply, "session_id": session_id}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint for Cloud Run."""
    return {"status": "ok"}



# ----------------------
# Startup Event
# ----------------------
@app.on_event("startup")
async def startup_event():
    """Log startup information."""
    logger.info("=" * 50)
    logger.info("nifty-bot-v3 starting up")
    logger.info(f"Ollama API key configured: {'Yes' if OLLAMA_API_KEY else 'No'}")
    logger.info(f"Database path: {DB_PATH}")
    logger.info("=" * 50)


# ----------------------
# Shutdown Event
# ----------------------
@app.on_event("shutdown")
async def shutdown_event():
    """Log shutdown information."""
    logger.info("nifty-bot-v3 shutting down")