from fastapi import FastAPI, Request, HTTPException
import os
import sqlite3
import secrets
import logging
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
ollama.set_api_key(OLLAMA_API_KEY)

app = FastAPI()