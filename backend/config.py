# backend/config.py - MODIFIED TO DECRYPT CONFIG ON STARTUP

import os
import logging
import urllib.parse
import json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from contextlib import contextmanager
from utils.decrypt_utils import decrypt_data  # Changed from relative import

# Load environment variables (for general, unencrypted app config like APP_HOST)
load_dotenv()

ENCRYPTED_CONFIG_PATH = os.getenv("ENCRYPTED_CONFIG_PATH", "encrypted_db_config.bin")
PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH", "private_key.pem") 

# -----------------------------
# Logging Configuration
# -----------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("config")

# -----------------------------
# Application Configuration (Read from unencrypted sources)
# -----------------------------
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", 7070))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# -----------------------------
# Encrypted Database Configuration Loader
# -----------------------------
def load_and_decrypt_db_config():
    """Loads and decrypts the database credentials from a secure file."""
    
    # 1. Check for required files
    if not os.path.exists(PRIVATE_KEY_PATH):
        logger.error(f"❌ Critical Error: RSA Private Key not found at {PRIVATE_KEY_PATH}")
        raise FileNotFoundError(f"RSA Private Key not found: {PRIVATE_KEY_PATH}. Ensure it is placed in the backend/ folder.")
    if not os.path.exists(ENCRYPTED_CONFIG_PATH):
        logger.error(f"❌ Critical Error: Encrypted config file not found at {ENCRYPTED_CONFIG_PATH}")
        raise FileNotFoundError(f"Encrypted config file not found: {ENCRYPTED_CONFIG_PATH}. Ensure the GUI tool saved it to the backend/ folder.")

    # 2. Load the encrypted payload string
    with open(ENCRYPTED_CONFIG_PATH, 'r') as f:
        encrypted_payload = f.read()

    # 3. Decrypt the payload
    try:
        decrypted_data = decrypt_data(encrypted_payload, PRIVATE_KEY_PATH)
        logger.info("✅ Database configuration decrypted successfully.")
        return decrypted_data
    except Exception as e:
        logger.error(f"❌ Decryption failed. Cannot start application. Error: {e}")
        # Stop the application if decryption fails (security measure)
        raise Exception("Failed to decrypt critical database configuration.")

# Load the decrypted configuration once when the module loads
DECRYPTED_DB_CONFIG = load_and_decrypt_db_config()

# -----------------------------
# Database Configuration (pulled from Decrypted Data)
# -----------------------------
DB_DRIVER = "{ODBC Driver 17 for SQL Server}" 
DB_SERVER = DECRYPTED_DB_CONFIG.get("DB_SERVER")
DB_NAME = DECRYPTED_DB_CONFIG.get("DB_NAME")
DB_USER = DECRYPTED_DB_CONFIG.get("DB_USER")
DB_PASSWORD = DECRYPTED_DB_CONFIG.get("DB_PASSWORD")
DB_TRUST_CERT = DECRYPTED_DB_CONFIG.get("DB_TRUST_CERT", "yes")

# -----------------------------
# ProServer Configuration (pulled from Decrypted Data)
# -----------------------------
PROSERVER_IP = DECRYPTED_DB_CONFIG.get("PROSERVER_IP")
PROSERVER_PORT = int(DECRYPTED_DB_CONFIG.get("PROSERVER_PORT", "7777"))

# -----------------------------
# Connection String Builder
# -----------------------------
def create_connection_string():
    """Builds a fully compatible SQL Server ODBC connection string for SQLAlchemy."""
    odbc_str = (
        f"DRIVER={DB_DRIVER};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        f"UID={DB_USER};"
        f"PWD={DB_PASSWORD};"
        f"Encrypt=no;"
        f"TrustServerCertificate={'yes' if DB_TRUST_CERT.lower() == 'yes' else 'no'};"
        f"Connection Timeout=30;"
    )

    params = urllib.parse.quote_plus(odbc_str)
    return f"mssql+pyodbc:///?odbc_connect={params}"

CONNECTION_STRING = create_connection_string()
logger.debug("Connection string created successfully")

# -----------------------------
# SQLAlchemy Engine Setup
# -----------------------------
try:
    engine = create_engine(
        CONNECTION_STRING,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,
    )
    logger.info("✅ SQLAlchemy engine created successfully")
except Exception as e:
    logger.error(f"❌ Error creating engine: {e}")
    raise

# -----------------------------
# Session Factory
# -----------------------------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
)

# -----------------------------
# Health Check Function
# -----------------------------
def health_check():
    """Verifies database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Database connection successful for health check")
        return True
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return False

# -----------------------------
# Context Manager for DB Sessions
# -----------------------------
@contextmanager
def get_db_connection():
    """Provides a transactional scope around DB operations."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -----------------------------
# Helper Query Functions
# -----------------------------
def fetch_one(query: str, params: dict = None):
    """Fetch a single row."""
    with engine.connect() as conn:
        result = conn.execute(text(query), params or {})
        row = result.fetchone()
        return dict(row._mapping) if row else None

def fetch_all(query: str, params: dict = None):
    """Fetch all rows."""
    with engine.connect() as conn:
        result = conn.execute(text(query), params or {})
        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]

def execute_query(query: str, params: dict = None):
    """Execute insert/update/delete query and return affected row count."""
    with engine.begin() as conn:
        result = conn.execute(text(query), params or {})
        return result.rowcount